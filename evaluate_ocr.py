"""
evaluate_ocr.py — โปรแกรมประเมินความถูกต้องของ OCR อัตโนมัติ (Automated OCR Evaluator)
รองรับทั้งการรันผ่าน Command Line (CLI) และโหมดถาม-ตอบ (Interactive Prompt)
"""

import os
import sys
import argparse
import difflib
from collections import Counter

try:
    import pypdfium2 as pdfium
    _HAS_PDFIUM = True
except ImportError:
    _HAS_PDFIUM = False

try:
    from pythainlp.tokenize import word_tokenize as thai_word_tokenize
    _HAS_PYTHAINLP = True
except ImportError:
    _HAS_PYTHAINLP = False

import pytesseract
from pytesseract import Output

from core.config import TESSERACT_CMD

# รองรับการ print ภาษาไทยและ UTF-8 บน Windows Console
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ==================== 1. OCR ENGINE EXTRACTION ====================

def extract_text_from_file(file_path: str) -> tuple[str, list[dict]]:
    """
    อ่านข้อความจากไฟล์ PDF หรือรูปภาพด้วย Tesseract OCR
    คืนค่า:
      - full_text: ข้อความทั้งหมด
      - line_details: ข้อความและค่า confidence แยกตามบรรทัด
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"ไม่พบไฟล์: {file_path}")

    _, ext = os.path.splitext(file_path)
    ext = ext.lower()
    if not TESSERACT_CMD:
        raise RuntimeError(
            "ไม่พบโปรแกรม Tesseract ในเครื่อง กรุณาติดตั้งและตั้งค่า TESSERACT_CMD ใน .env"
        )
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

    images = []

    if ext == ".pdf":
        if not _HAS_PDFIUM:
            raise RuntimeError("จำเป็นต้องใช้ pypdfium2 ในการอ่านไฟล์ PDF")
        pdf = pdfium.PdfDocument(file_path)
        try:
            for page_idx in range(len(pdf)):
                page = pdf[page_idx]
                try:
                    pil_image = page.render(scale=2.0).to_pil()
                    images.append((page_idx + 1, pil_image))
                finally:
                    page.close()
        finally:
            pdf.close()
    elif ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"]:
        from PIL import Image
        with Image.open(file_path) as pil_img:
            images.append((1, pil_img.convert("RGB")))
    else:
        raise ValueError(f"นามสกุลไฟล์ {ext} ยังไม่รองรับ (รองรับ PDF, PNG, JPG, JPEG)")

    all_lines = []
    line_details = []

    for page_num, image in images:
        page_text = pytesseract.image_to_string(image, lang="tha+eng")
        ocr_lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        results = pytesseract.image_to_data(
            image,
            lang="tha+eng",
            output_type=Output.DICT,
        )
        line_confidences = {}
        for index, text in enumerate(results["text"]):
            text = text.strip()
            confidence = float(results["conf"][index])
            if not text or confidence < 0:
                continue
            line_key = (
                results["block_num"][index],
                results["par_num"][index],
                results["line_num"][index],
            )
            line_confidences.setdefault(line_key, []).append(confidence)

        confidences = [
            sum(values) / len(values) for values in line_confidences.values()
        ]
        for line_index, line_text in enumerate(ocr_lines):
            confidence = (
                confidences[line_index] if line_index < len(confidences) else None
            )
            all_lines.append(line_text)
            line_details.append(
                {"page": page_num, "text": line_text, "confidence": confidence}
            )

    full_text = "\n".join(all_lines)
    return full_text, line_details


# ==================== 2. EVALUATION METRICS ====================

def calculate_levenshtein(s1: str, s2: str) -> int:
    """คำนวณ Levenshtein Edit Distance ระดับตัวอักษร"""
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1): dp[i][0] = i
    for j in range(n + 1): dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[m][n]


def evaluate_ocr_against_gt(gt_text: str, ocr_text: str) -> dict:
    """
    เปรียบเทียบข้อความต้นฉบับจริง (Ground Truth) กับผลลัพธ์ของ OCR
    """
    gt_lines = [l.strip() for l in gt_text.splitlines() if l.strip()]
    ocr_lines = [l.strip() for l in ocr_text.splitlines() if l.strip()]

    # 1. การจับคู่ประโยคที่ใกล้เคียงที่สุด (Best Line Matching)
    matched_pairs = []
    used_ocr_indices = set()

    for gt_idx, g_line in enumerate(gt_lines):
        best_match_idx = -1
        best_ratio = -1.0
        for o_idx, o_line in enumerate(ocr_lines):
            ratio = difflib.SequenceMatcher(None, g_line.lower(), o_line.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match_idx = o_idx

        # ถ้าคะแนน match เกิน 0.2 ให้จับคู่กัน
        if best_match_idx != -1 and best_ratio >= 0.2:
            matched_pairs.append((g_line, ocr_lines[best_match_idx]))
            used_ocr_indices.add(best_match_idx)
        else:
            matched_pairs.append((g_line, ""))

    # 2. คำนวณความถูกต้องรายประโยค
    line_results = []
    total_ref_chars = 0
    total_correct_chars = 0
    total_edit_dist = 0
    sub_pairs = []

    for idx, (ref, hyp) in enumerate(matched_pairs, 1):
        r_clean = "".join(c.lower() for c in ref if not c.isspace())
        h_clean = "".join(c.lower() for c in hyp if not c.isspace())

        matcher = difflib.SequenceMatcher(None, r_clean, h_clean)
        correct = sum(match.size for match in matcher.get_matching_blocks())
        r_len = len(r_clean)

        dist = calculate_levenshtein(r_clean, h_clean)
        total_ref_chars += r_len
        total_correct_chars += correct
        total_edit_dist += dist

        acc = (correct / r_len * 100) if r_len > 0 else 0.0
        cer = (dist / r_len * 100) if r_len > 0 else 0.0

        # บันทึกจุดคลาดเคลื่อน (Diff Notes) และความสับสนของตัวอักษร
        diff_notes = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "replace":
                r_chunk = r_clean[i1:i2]
                h_chunk = h_clean[j1:j2]
                diff_notes.append(f"'{r_chunk}' -> '{h_chunk}'")
                if len(r_chunk) == len(h_chunk):
                    for rc, hc in zip(r_chunk, h_chunk):
                        if rc != hc:
                            sub_pairs.append((rc, hc))
            elif tag == "delete":
                diff_notes.append(f"ขาด '{r_clean[i1:i2]}'")
            elif tag == "insert":
                diff_notes.append(f"เกิน '{h_clean[j1:j2]}'")

        line_results.append({
            "index": idx,
            "ref": ref,
            "hyp": hyp,
            "ref_len": r_len,
            "correct": correct,
            "edit_dist": dist,
            "accuracy": acc,
            "cer": cer,
            "diff_notes": diff_notes
        })

    # 3. คำนวณสถิติระดับคำ (Word Accuracy)
    # ตรวจสอบว่าเป็นภาษาไทยหรือไม่ เพื่อเลือกวิธีตัดคำที่ถูกต้อง (Thai Word Tokenization)
    is_thai = any("\u0e00" <= c <= "\u0e7f" for c in gt_text)
    if is_thai and _HAS_PYTHAINLP:
        ref_tokens = thai_word_tokenize(gt_text, keep_whitespace=False)
        ocr_tokens = thai_word_tokenize(ocr_text, keep_whitespace=False)
        ref_words = [w.lower().strip(".,!?:;\"'()[]") for w in ref_tokens if w.strip(".,!?:;\"'()[]")]
        hyp_words = set(w.lower().strip(".,!?:;\"'()[]") for w in ocr_tokens if w.strip(".,!?:;\"'()[]"))
        tokenizer_used = "PyThaiNLP (การตัดคำภาษาไทย)"
    else:
        ref_words = [w.lower().strip(".,!?:;\"'()[]") for w in gt_text.split() if w.strip()]
        hyp_words = set(w.lower().strip(".,!?:;\"'()[]") for w in ocr_text.split() if w.strip())
        tokenizer_used = "Whitespace / เคาะวรรค (ภาษาอังกฤษ)"

    matched_word_count = sum(1 for w in ref_words if w in hyp_words)
    total_word_count = len(ref_words)
    word_accuracy = (matched_word_count / total_word_count * 100) if total_word_count > 0 else 0.0

    # 4. สรุปตัวเลขภาพรวม
    overall_char_accuracy = (total_correct_chars / total_ref_chars * 100) if total_ref_chars > 0 else 0.0
    overall_cer = (total_edit_dist / total_ref_chars * 100) if total_ref_chars > 0 else 0.0
    confusion_matrix = Counter(sub_pairs).most_common(12)

    return {
        "total_ref_chars": total_ref_chars,
        "total_correct_chars": total_correct_chars,
        "total_edit_dist": total_edit_dist,
        "overall_char_accuracy": overall_char_accuracy,
        "overall_cer": overall_cer,
        "total_words": total_word_count,
        "matched_words": matched_word_count,
        "word_accuracy": word_accuracy,
        "tokenizer_used": tokenizer_used,
        "line_results": line_results,
        "confusion_matrix": confusion_matrix
    }


# ==================== 3. REPORT GENERATOR ====================

def generate_report_content(file_path: str, ocr_text: str, eval_data: dict | None) -> str:
    """สร้างเนื้อหารายงานสรุปในรูปแบบ Text"""
    filename = os.path.basename(file_path)
    lines = []
    lines.append("=" * 90)
    lines.append(f"รายงานผลการทดสอบและประเมินประสิทธิภาพ OCR (OCR Evaluation Report)")
    lines.append(f"ไฟล์เอกสาร: {filename}")
    lines.append("=" * 90)
    lines.append("")

    if eval_data:
        lines.append("[1] สรุปสถิติความถูกต้องภาพรวม (Executive Summary)")
        lines.append("-" * 90)
        lines.append(f"- โหมดการคำนวณตัวอักษร:            ไม่นับเว้นวรรคและช่องว่าง (Ignored Whitespace)")
        lines.append(f"- วิธีการตัดคำ (Tokenization):       {eval_data.get('tokenizer_used', '-')}")
        lines.append(f"- ความถูกต้องระดับคำ (Word Accuracy):        {eval_data['word_accuracy']:.2f}% ({eval_data['matched_words']}/{eval_data['total_words']} คำ)")
        lines.append(f"- ความถูกต้องระดับตัวอักษร (Char Accuracy):    {eval_data['overall_char_accuracy']:.2f}% ({eval_data['total_correct_chars']}/{eval_data['total_ref_chars']} ตัวอักษร)")
        lines.append(f"- อัตราความผิดพลาดตัวอักษร (CER):             {eval_data['overall_cer']:.2f}% (จุดคลาดเคลื่อน {eval_data['total_edit_dist']} จุด)")
        lines.append(f"- จำนวนตัวอักษรต้นฉบับ (ไม่รวมเคาะวรรค):      {eval_data['total_ref_chars']} ตัวอักษร")
        lines.append(f"- จำนวนตัวอักษรที่อ่านถูกต้องตรงตำแหน่งเป๊ะ:    {eval_data['total_correct_chars']} ตัวอักษร")
        lines.append("")

        lines.append("[2] การวิเคราะห์ความถูกต้องรายประโยค / รายบรรทัด (Line-by-Line Breakdown)")
        lines.append("-" * 90)
        for row in eval_data["line_results"]:
            lines.append(f"{row['index']:2d}. ต้นฉบับ: \"{row['ref']}\"")
            lines.append(f"    OCR:    \"{row['hyp']}\"")
            lines.append(f"    สถิติ:  ความแม่นยำ {row['accuracy']:.1f}% | CER {row['cer']:.1f}% (ถูก {row['correct']}/{row['ref_len']} ตัว, ผิด {row['edit_dist']})")
            if row.get("diff_notes"):
                lines.append(f"    จุดที่ผิด: {', '.join(row['diff_notes'][:6])}")
            else:
                lines.append(f"    จุดที่ผิด: ไม่มี (ถูกต้อง 100%)")
            lines.append("")

        if eval_data["confusion_matrix"]:
            lines.append("[3] ตัวอักษรที่เกิดความสับสนบ่อยที่สุด (Character Confusion Matrix)")
            lines.append("-" * 90)
            lines.append(f"{'ตัวอักษรจริง':^15} -> {'ตัวที่อ่านได้':^15} | {'จำนวนครั้ง':^12}")
            lines.append("-" * 50)
            for (rc, hc), cnt in eval_data["confusion_matrix"]:
                lines.append(f"{rc:^15} -> {hc:^15} | {cnt:^12} ครั้ง")
            lines.append("")

    lines.append("=" * 90)
    lines.append("[4] ข้อความเต็มที่ OCR สกัดออกมาได้ (Full Extracted OCR Text)")
    lines.append("-" * 90)
    lines.append(ocr_text)
    lines.append("=" * 90)

    return "\n".join(lines)


# ==================== 4. MAIN ENTRY POINT ====================

def main():
    parser = argparse.ArgumentParser(description="OCR Automatic Evaluation & Report Generator")
    parser.add_argument("file_path", nargs="?", help="Path ไปยังไฟล์ PDF หรือรูปภาพที่ต้องการ OCR")
    parser.add_argument("--gt", "--ground-truth", dest="gt_path", help="Path ไปยังไฟล์ข้อความต้นฉบับ (Ground Truth .txt)")
    parser.add_argument("-o", "--output", dest="output_path", help="Path สำหรับบันทึกรายงานผล (เช่น report.txt)")
    args = parser.parse_args()

    input_file = args.file_path
    gt_file = args.gt_path
    output_file = args.output_path

    # ถ้าไม่ได้ใส่ argument ให้เข้า Interactive Mode ถามทีละข้อ
    if not input_file:
        print("=" * 60)
        print("[*] โปรแกรมสร้างรายงานประเมินความถูกต้องของ OCR")
        print("=" * 60)
        input_file = input("กรุณาระบุ Path ของไฟล์ PDF หรือรูปภาพที่ต้องการ OCR: ").strip().strip('"').strip("'")
        if not input_file:
            print("[-] ไม่ได้ระบุไฟล์ ยกเลิกการทำงาน")
            sys.exit(1)

        gt_input = input("กรุณาระบุ Path ของไฟล์ข้อความต้นฉบับ Ground Truth (.txt) [กด Enter หากไม่มี]: ").strip().strip('"').strip("'")
        if gt_input:
            gt_file = gt_input

    if not os.path.exists(input_file):
        print(f"[-] ไม่พบไฟล์: {input_file}")
        sys.exit(1)

    print(f"\n[*] กำลังประมวลผล OCR บนไฟล์: {os.path.basename(input_file)} ...")
    try:
        ocr_text, line_details = extract_text_from_file(input_file)
    except Exception as e:
        print(f"[-] เกิดข้อผิดพลาดในการรัน OCR: {e}")
        sys.exit(1)

    eval_data = None
    if gt_file and os.path.exists(gt_file):
        print(f"[*] กำลังเปรียบเทียบกับ Ground Truth: {os.path.basename(gt_file)} ...")
        with open(gt_file, "r", encoding="utf-8") as f:
            gt_text = f.read()
        eval_data = evaluate_ocr_against_gt(gt_text, ocr_text)

    # กำหนดตำแหน่งบันทึกไฟล์รายงาน
    if not output_file:
        base_name, _ = os.path.splitext(os.path.basename(input_file))
        output_file = f"{base_name}_ocr_evaluation_report.txt"

    report_content = generate_report_content(input_file, ocr_text, eval_data)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(report_content)

    print("\n" + "=" * 60)
    print("[+] สร้างรายงานผลสำเร็จเรียบร้อยแล้ว!")
    print(f"    บันทึกรายงานไว้ที่: {os.path.abspath(output_file)}")
    print("=" * 60)

    if eval_data:
        print(f"  - ความถูกต้องระดับคำ (Word Accuracy):        {eval_data['word_accuracy']:.2f}%")
        print(f"  - ความถูกต้องระดับตัวอักษร (Char Accuracy):    {eval_data['overall_char_accuracy']:.2f}%")
        print(f"  - อัตราความผิดพลาดตัวอักษร (CER):             {eval_data['overall_cer']:.2f}%")
        print(f"  - จุดคลาดเคลื่อนรวม:                          {eval_data['total_edit_dist']} จุด")
    else:
        print(f"  - สกัดข้อความได้ทั้งหมด:                       {len(ocr_text)} ตัวอักษร")
        print("  (หมายเหตุ: หากต้องการเปอร์เซ็นต์ความถูกต้อง กรุณาระบุไฟล์ --gt <ไฟล์ต้นฉบับ.txt>)")


if __name__ == "__main__":
    main()
