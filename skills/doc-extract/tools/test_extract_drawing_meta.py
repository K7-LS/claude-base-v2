import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from extract_drawing_meta import extract_text_blocks, find_stamp_data

def test_extract_text_blocks_from_pdf():
    """Проверяем что blocks возвращаются с координатами."""
    import glob
    pdfs = glob.glob("knowledge/**/*.pdf", recursive=True)
    if not pdfs:
        print("SKIP: no test PDF found in knowledge/")
        return
    test_pdf = pdfs[0]
    blocks = extract_text_blocks(test_pdf, page=0)
    assert isinstance(blocks, list)
    if blocks:
        b = blocks[0]
        assert "text" in b and "bbox" in b
        assert isinstance(b["bbox"], tuple) and len(b["bbox"]) == 4
    print(f"OK: test_extract_text_blocks_from_pdf ({len(blocks)} blocks)")

def test_find_stamp_data_returns_dict():
    """Стамп должен вернуть dict с ключами project, drawing_no, scale (или None)."""
    blocks = [
        {"text": "ООО <организация>", "bbox": (450, 50, 550, 65)},
        {"text": "Проект: TEST-1", "bbox": (450, 70, 580, 85)},
        {"text": "Лист: 5", "bbox": (450, 100, 500, 115)},
    ]
    stamp = find_stamp_data(blocks, page_size=(595, 842))
    assert isinstance(stamp, dict)
    assert "project" in stamp
    print("OK: test_find_stamp_data_returns_dict")

if __name__ == "__main__":
    test_extract_text_blocks_from_pdf()
    test_find_stamp_data_returns_dict()
