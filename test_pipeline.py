import os
import sys
import shutil

if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from printflow.core.prepress import extract_image_and_mask, generate_previews, export_job_plates
from printflow.core.router import HotFolderRouter

def test_full_pipeline():
    print("=" * 70)
    print("TESTING PRINTFLOW PRO END-TO-END PIPELINE")
    print("=" * 70)
    
    test_pdf = "Untitled-1.pdf"
    assert os.path.exists(test_pdf), "Untitled-1.pdf must exist"
    
    router = HotFolderRouter("printflow/config/presets.json")
    products = router.get_products()
    print(f"Loaded {len(products)} products from presets.json")
    
    # Test Inspect
    print("\n1. Testing Image & Mask Extraction...")
    img_rgb, is_graphic, w_pt, h_pt = extract_image_and_mask(test_pdf, dpi=300)
    print(f"   Image size: {img_rgb.size}, Points: {w_pt:.2f} x {h_pt:.2f} pt")
    
    print("\n2. Testing Preview Generation...")
    previews = generate_previews(img_rgb, is_graphic, choke_pixels=1)
    assert "composite" in previews
    assert "white" in previews
    assert "primer" in previews
    print("   Previews generated successfully (Base64 ready for Web UI).")
    
    # Test Export & Dispatch for all products
    print("\n3. Testing Export & Hot Folder Dispatch for all products...")
    temp_dir = "printflow/temp_test_out"
    os.makedirs(temp_dir, exist_ok=True)
    
    for product in products:
        p_id = product["id"]
        job_id = f"TEST_{p_id.upper()}_001"
        print(f"\n   --> Testing Product: {product['name']} (ID: {p_id})")
        
        # Export
        plates = export_job_plates(job_id, test_pdf, product, temp_dir)
        print(f"       Generated plates: {list(plates.keys())}")
        for layer, path in plates.items():
            assert os.path.exists(path), f"File {path} does not exist"
            print(f"       [OK] {layer}: {os.path.basename(path)} ({os.path.getsize(path)} bytes)")
            
        # Dispatch
        dispatched = router.dispatch_plates(job_id, product, plates)
        print(f"       Dispatched {len(dispatched)} files to Hot Folders:")
        for d in dispatched:
            assert os.path.exists(d["destination"]), f"Hotfolder file missing: {d['destination']}"
            print(f"       [DISPATCHED] -> {d['destination']}")
            
    # Cleanup test output
    shutil.rmtree(temp_dir, ignore_errors=True)
    print("\n" + "=" * 70)
    print("ALL PIPELINE TESTS PASSED 100% SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    test_full_pipeline()
