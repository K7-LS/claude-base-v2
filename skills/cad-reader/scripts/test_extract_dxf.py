import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from extract_dxf import list_layers, extract_text_entities, find_stamp

TEST_DXF = "artifacts/smoketest/test_drawing.dxf"

def test_list_layers():
    layers = list_layers(TEST_DXF)
    assert "rooms" in layers
    assert "SKS" in layers or "sks" in {l.lower() for l in layers}
    assert "stamp" in layers
    print(f"OK: test_list_layers ({layers})")

def test_extract_text_entities_finds_room_label():
    texts = extract_text_entities(TEST_DXF, layer="rooms")
    assert any("Помещение" in t["text"] for t in texts), [t["text"] for t in texts]
    print(f"OK: test_extract_text_entities_finds_room_label")

def test_find_stamp():
    stamp = find_stamp(TEST_DXF, stamp_layer="stamp")
    assert stamp.get("project") == "TEST-1", stamp
    assert stamp.get("drawing_no") == "5", stamp
    print(f"OK: test_find_stamp ({stamp})")

if __name__ == "__main__":
    test_list_layers()
    test_extract_text_entities_finds_room_label()
    test_find_stamp()
