import os
import io
import json
import re
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from PIL import Image
import google.generativeai as genai

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-3.1-flash-Lite")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB max

SYSTEM_PROMPT = """You are a receipt parser. Extract data from this food delivery receipt image (may be in Chinese or English) and return ONLY valid JSON.

Return this exact structure:
{
  "platform": "FoodPanda",
  "date": "2026-06-16",
  "items": [
    {"name": "Item name", "option": "add-on option or empty string", "price": 53.0}
  ],
  "subtotal": 392.0,
  "discount": 78.4,
  "platform_fee": 5.0,
  "coupon": 30.0,
  "total": 288.6
}

Rules:
- price is the item's listed price (before discount)
- subtotal = sum of all item prices before any discount (小計)
- discount = positive number (the amount deducted, 折扣優惠)
- coupon = positive number (the amount deducted, 優惠券), 0 if none
- platform_fee = 平台費, 0 if none
- total = final amount paid (總計)
- If a field is not on the receipt, use 0
- For item options (附加選項), include drink choices, noodle type, etc.
- Return ONLY the JSON, no markdown, no explanation"""


def parse_receipt(image_bytes: bytes) -> dict:
    img = Image.open(io.BytesIO(image_bytes))
    response = model.generate_content([SYSTEM_PROMPT, img])
    raw = response.text.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("```").strip()
    return json.loads(raw)


def calculate(data: dict) -> list:
    subtotal = data["subtotal"]
    total = data["total"]
    items = []
    for item in data["items"]:
        after = round(item["price"] / subtotal * total, 1) if subtotal else 0
        items.append({**item, "after_discount": after})
    return items


def build_html(data: dict, items: list) -> str:
    date = data.get("date", datetime.today().strftime("%Y-%m-%d"))
    platform = data.get("platform", "Food Delivery")
    rows = ""
    for item in items:
        option = item.get("option") or "—"
        rows += f"""
        <tr>
          <td>{item['name']}</td>
          <td>{option}</td>
          <td>{item['price']:.1f}</td>
          <td>{item['after_discount']:.1f}</td>
        </tr>"""

    discount = data.get("discount", 0)
    platform_fee = data.get("platform_fee", 0)
    coupon = data.get("coupon", 0)
    subtotal = data.get("subtotal", 0)
    total = data.get("total", 0)
    coupon_row = f'<tr><td>Coupon</td><td class="discount">− HK$ {coupon:.1f}</td></tr>' if coupon else ""

    return f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Receipt Breakdown</title>
<style>
  body {{ font-family: "PingFang HK", "Microsoft JhengHei", Arial, sans-serif;
         max-width: 700px; margin: 40px auto; padding: 0 20px; color: #222; }}
  h1 {{ text-align: center; color: #C62828; margin-bottom: 4px; }}
  .subtitle {{ text-align: center; color: #888; font-size: 14px; margin-bottom: 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; }}
  thead tr {{ background: #E53935; color: #fff; }}
  th {{ padding: 10px 12px; text-align: left; font-size: 14px; }}
  th:nth-child(3), th:nth-child(4) {{ text-align: right; }}
  td {{ padding: 9px 12px; font-size: 14px; border-bottom: 1px solid #eee; }}
  td:nth-child(3), td:nth-child(4) {{ text-align: right; }}
  tr:nth-child(even) {{ background: #FFF5F5; }}
  .summary {{ width: 60%; margin-left: auto; }}
  .summary td {{ font-size: 14px; padding: 7px 12px; border-bottom: 1px solid #eee; }}
  .summary td:last-child {{ text-align: right; }}
  .discount {{ color: #C62828; }}
  .total-row {{ background: #FFEBEE; font-weight: 700; font-size: 15px; }}
  .notes {{ color: #aaa; font-size: 12px; margin-top: 16px; }}
</style>
</head>
<body>
<h1>Receipt Breakdown</h1>
<div class="subtitle">{date} &nbsp;|&nbsp; {platform}</div>
<table>
  <thead>
    <tr><th>Item</th><th>Option</th><th>Price (HK$)</th><th>After Discount (HK$)</th></tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
<table class="summary">
  <tr><td>Subtotal</td><td>HK$ {subtotal:.1f}</td></tr>
  <tr><td>Discount</td><td class="discount">− HK$ {discount:.1f}</td></tr>
  <tr><td>Platform Fee</td><td>+ HK$ {platform_fee:.1f}</td></tr>
  {coupon_row}
  <tr class="total-row"><td>Total (incl. tax)</td><td>HK$ {total:.1f}</td></tr>
</table>
<div class="notes">
  * After-discount price = item price ÷ subtotal × total<br>
  * Payment: Credit Card
</div>
</body>
</html>"""


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/process", methods=["POST"])
def process():
    if "image" not in request.files:
        return jsonify({"error": "No image uploaded"}), 400

    file = request.files["image"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if file.mimetype not in allowed:
        return jsonify({"error": f"Unsupported file type: {file.mimetype}"}), 400

    try:
        image_bytes = file.read()
        data = parse_receipt(image_bytes)
        items = calculate(data)
        html = build_html(data, items)
        return jsonify({"html": html, "data": data, "items": items})
    except json.JSONDecodeError as e:
        return jsonify({"error": f"Failed to parse receipt data: {e}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
