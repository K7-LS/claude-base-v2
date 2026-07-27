import sys, os, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from upload import resolve_target_path, FileType

def test_resolve_target_path_contract():
    p = resolve_target_path(project_code="TEST-1", file_type=FileType.CONTRACT, filename="договор.pdf")
    assert p == "02_Проекты/TEST-1/02_Договор/договор.pdf", p
    print("OK: test_resolve_target_path_contract")

def test_resolve_target_path_invoice():
    p = resolve_target_path(project_code="TEST-2", file_type=FileType.INVOICE, filename="счёт_001.pdf")
    assert p == "02_Проекты/TEST-2/03_Финансы/счёт_001.pdf"
    print("OK: test_resolve_target_path_invoice")

def test_resolve_target_path_correspondence():
    p = resolve_target_path(project_code="TEST-1", file_type=FileType.CORRESPONDENCE, filename="ответ.docx")
    assert p == "02_Проекты/TEST-1/02_Договор/05_Переписка/ответ.docx"
    print("OK: test_resolve_target_path_correspondence")

def test_resolve_target_path_unknown_project_raises():
    try:
        resolve_target_path(project_code="", file_type=FileType.CONTRACT, filename="x.pdf")
        assert False, "Expected ValueError"
    except ValueError:
        print("OK: test_resolve_target_path_unknown_project_raises")

if __name__ == "__main__":
    test_resolve_target_path_contract()
    test_resolve_target_path_invoice()
    test_resolve_target_path_correspondence()
    test_resolve_target_path_unknown_project_raises()
