import sys
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fastapi.testclient import TestClient
from printflow.server.app import app

client = TestClient(app)

print("1. Testing GET /api/presets...")
r = client.get("/api/presets")
assert r.status_code == 200
presets = r.json()
print(f"   Presets loaded: {len(presets.get('products', []))} products")

print("\n2. Testing GET /api/status...")
r = client.get("/api/status")
assert r.status_code == 200
print(f"   System Status: {r.json()}")

print("\n3. Testing POST /api/inspect with Untitled-1.pdf...")
with open("Untitled-1.pdf", "rb") as f:
    r = client.post(
        "/api/inspect",
        files={"file": ("Untitled-1.pdf", f, "application/pdf")},
        data={"product_id": "acrylic_3layer", "choke_pixels": "1"}
    )
assert r.status_code == 200, f"Inspect failed: {r.text}"
inspect_res = r.json()
print(f"   Inspect status: {inspect_res['status']}")
print(f"   Dimensions: {inspect_res['width_mm']} x {inspect_res['height_mm']} mm")
print(f"   Previews available: {list(inspect_res['previews'].keys())}")

print("\n4. Testing POST /api/print...")
r = client.post(
    "/api/print",
    data={
        "temp_file_id": inspect_res["temp_file_id"],
        "product_id": "acrylic_3layer",
        "order_number": "ORD-2026-9999",
        "copies": "2"
    }
)
assert r.status_code == 200, f"Print failed: {r.text}"
print_res = r.json()
print(f"   Print status: {print_res['status']}")
print(f"   Job ID: {print_res['job_id']}")
print(f"   Execution time: {print_res['elapsed_ms']} ms")
print(f"   Dispatched plates count: {len(print_res['dispatched'])}")

print("\n5. Testing GET /api/history...")
r = client.get("/api/history")
assert r.status_code == 200
history = r.json()
print(f"   History count: {len(history)}")
print(f"   Latest job: {history[0]['job_id']} -> {history[0]['product_name']} ({history[0]['layers']})")

print("\n" + "=" * 70)
print("ALL SERVER & API ENDPOINTS VERIFIED 100% SUCCESSFULLY!")
print("=" * 70)
