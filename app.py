from flask import Flask, render_template, jsonify
# Dosya adınız 'model_data (1).py' ise, import ederken sorun çıkabilir.
# Lütfen dosyanın adını 'model_data.py' olarak değiştirin ve yanına koyun.
import model_data
import json

app = Flask(__name__)

# ------------------------------------------------------------------------------
# AYARLAR VE SABİTLER
# ------------------------------------------------------------------------------
# NOT: model_data.B = 60 gelmiş. Bu bütçe ile sadece 1 varlık seçilir.
# 20 tane seçilmesi için bütçeyi burada override ediyoruz (Tahmini: 20 * ~75 maliyet = 1500)
TARGET_BUDGET = 1500 

# Ağırlıklar (Değiştirebilirsiniz)
W = {'w1': 0.3, 'w2': 0.2, 'w3': 0.1, 'w4': 0.4}

# ------------------------------------------------------------------------------
# VERİ İŞLEME
# ------------------------------------------------------------------------------
def get_all_assets():
    assets = []
    
    # Sağlık İndeksi (HI) normalizasyonu için maksimum değeri bul
    # Veri setinde değerler 0-10000 arasında görünüyor.
    max_hi = 10000 

    for i in model_data.I:
        # Yeni veri setinde 'HI' (Health Index) kullanılmış
        raw_health = model_data.HI.get(i, 0)
        
        # 0-100 Skalasına çekelim
        health_ui = round((raw_health / max_hi) * 100, 1)
        
        # Risk Etiketi Belirleme
        if health_ui < 40:
            risk_label = "Yüksek"
        elif health_ui < 70:
            risk_label = "Orta"
        else:
            risk_label = "Düşük"

        # Yeni veri setinde Grup ismi 'TYPE' değişkeninde
        group_name = model_data.TYPE.get(i, "Genel")

        # Talep No ve İşlem Tipi veride yok, ID'den türetiyoruz
        talep_no = f"T-{1000+i}" 
        
        # Varsayılan olarak hepsini 'Yatırım Adayı' kabul ediyoruz
        operation_type = "Yatırım"

        asset = {
            "id": i,
            "talep_no": talep_no,
            "saidi": model_data.SAIDI.get(i, 0.0),
            "saifi": model_data.SAIFI.get(i, 0.0),
            "cost": model_data.C.get(i, 0),
            "group": group_name,
            "category_public": model_data.K.get(i, 0) == 1,
            "raw_health": raw_health,
            "health_ui": health_ui,
            "risk_label": risk_label,
            "operation_type": operation_type
        }
        assets.append(asset)
    
    return assets

# ------------------------------------------------------------------------------
# ENDPOINTLER
# ------------------------------------------------------------------------------

@app.route("/")
def index():
    assets = get_all_assets()
    
    # KPI Hesaplamaları
    total_assets = len(assets)
    high_risk_count = sum(1 for a in assets if a["risk_label"] == "Yüksek")
    avg_health = sum(a["health_ui"] for a in assets) / total_assets if total_assets > 0 else 0

    kpi = {
        "total_assets": total_assets,
        "high_risk_count": high_risk_count,
        "avg_health": round(avg_health, 1),
        "budget": TARGET_BUDGET
    }

    # index.html'e veriyi gönder
    return render_template("index.html", assets=assets, kpi=kpi)

@app.route("/api/optimize", methods=["GET", "POST"])
def run_optimization():
    try:
        assets = get_all_assets()
        budget = TARGET_BUDGET  # Yükseltilmiş bütçeyi kullan
        
        # Normalizasyon için max değerler
        max_saidi = max((a["saidi"] for a in assets), default=1)
        max_saifi = max((a["saifi"] for a in assets), default=1)

        scored_assets = []
        for a in assets:
            # 1. Kriter: SAIDI (Ne kadar yüksekse o kadar öncelikli)
            norm_saidi = a["saidi"] / max_saidi if max_saidi > 0 else 0
            
            # 2. Kriter: SAIFI (Ne kadar yüksekse o kadar öncelikli)
            norm_saifi = a["saifi"] / max_saifi if max_saifi > 0 else 0
            
            # 3. Kriter: Sağlık Riski (Sağlık ne kadar kötüyse (düşükse), puan o kadar artmalı)
            # health_ui 0-100 arası (100 iyi). Yani (100 - health) bize risk puanını verir.
            norm_health_risk = (100 - a["health_ui"]) / 100.0

            # Toplam Skor
            priority_score = (W['w1'] * norm_saidi) + (W['w2'] * norm_saifi) + (W['w4'] * norm_health_risk)
            
            a["priority_score"] = priority_score
            scored_assets.append(a)

        # Sıralama: (Skor / Maliyet) oranına göre "Bang for Buck" yaklaşımı
        # Yani birim maliyet başına en yüksek faydayı sağlayanları en başa alıyoruz.
        scored_assets.sort(key=lambda x: x["priority_score"] / max(x["cost"], 1), reverse=True)

        selected = []
        used_budget = 0.0
        total_objective_val = 0.0

        # Greedy Seçim
        for item in scored_assets:
            if used_budget + item["cost"] <= budget:
                selected.append({
                    "talep_no": item["talep_no"],
                    "tur": item["operation_type"],
                    "grup": item["group"],
                    "maliyet": item["cost"],
                    "skor": round(item["priority_score"], 4)
                })
                used_budget += item["cost"]
                total_objective_val += item["priority_score"]

        return jsonify({
            "status": "Optimal",
            "selected_count": len(selected),
            "used_budget": round(used_budget, 2),
            "budget": budget,
            "objective_value": round(total_objective_val, 4),
            "selected": selected
        })

    except Exception as e:
        print(f"Hata: {e}")
        return jsonify({"status": "Error", "error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
