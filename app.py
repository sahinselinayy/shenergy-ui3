from flask import Flask, render_template, jsonify
import model_data  # model_data.py dosyasının yanında olduğundan emin olun
import json

app = Flask(__name__)

# ------------------------------------------------------------------------------
# AYARLAR
# ------------------------------------------------------------------------------
# Model dosyasında Bütçe=60 verilmiş. 20 tane varlık seçtirmek için
# bütçeyi burada override ediyoruz (Yaklaşık 20 varlık x 75 maliyet = 1500)
TARGET_BUDGET = 1500 

# Ağırlıklar (Yatırım önceliklendirme için)
W = {'w1': 0.3, 'w2': 0.2, 'w3': 0.1, 'w4': 0.4}

# ------------------------------------------------------------------------------
# VERİ İŞLEME KATMANI
# ------------------------------------------------------------------------------
def get_all_assets():
    assets = []
    
    # Sağlık İndeksi (HI) normalizasyonu için maksimum değer (Veride 10000 görünüyor)
    max_hi = 10000 

    for i in model_data.I:
        # 1. SAĞLIK VERİSİ (HI)
        # Yeni dosyada A yerine HI kullanılmış
        raw_health = model_data.HI.get(i, 0)
        
        # 0-100 Skalasına çekelim (UI'da göstermek için)
        health_ui = round((raw_health / max_hi) * 100, 1)
        
        # Risk Etiketi Belirleme (Düşük Sağlık = Yüksek Risk)
        if health_ui < 40:
            risk_label = "Yüksek"
        elif health_ui < 70:
            risk_label = "Orta"
        else:
            risk_label = "Düşük"

        # 2. GRUP VERİSİ (TYPE)
        # Yeni dosyada G yerine TYPE kullanılmış
        group_name = model_data.TYPE.get(i, "Genel")

        # 3. DİĞER VERİLER
        # Talep No veri setinde yoksa ID'den türetelim
        talep_no = f"T-{1000+i}" 
        
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
            "operation_type": "Yatırım" # Varsayılan
        }
        assets.append(asset)
    
    return assets

# ------------------------------------------------------------------------------
# ROTALAR
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

    # Frontend'e veriyi gönderiyoruz
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
            # Skorlama Mantığı:
            # SAIDI/SAIFI yüksekse -> Öncelik artar
            # Sağlık DÜŞÜKSE -> Öncelik artar ((100 - health) formülü)
            
            norm_saidi = a["saidi"] / max_saidi if max_saidi > 0 else 0
            norm_saifi = a["saifi"] / max_saifi if max_saifi > 0 else 0
            norm_health_risk = (100 - a["health_ui"]) / 100.0

            priority_score = (W['w1'] * norm_saidi) + (W['w2'] * norm_saifi) + (W['w4'] * norm_health_risk)
            
            a["priority_score"] = priority_score
            scored_assets.append(a)

        # "Fayda / Maliyet" oranına göre sırala (En verimli yatırımlar en başa)
        scored_assets.sort(key=lambda x: x["priority_score"] / max(x["cost"], 1), reverse=True)

        selected = []
        used_budget = 0.0
        total_objective_val = 0.0

        # Bütçe dolana kadar en iyileri seç
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
