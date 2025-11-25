from flask import Flask, render_template, jsonify
import model_data
import json

app = Flask(__name__)

# ------------------------------------------------------------------------------
# VERİ İŞLEME KATMANI
# ------------------------------------------------------------------------------
def get_all_assets():
    """
    model_data.py içindeki ayrık sözlük yapılarını (I, SAIDI, C, A vb.)
    tek bir liste haline getirir.
    """
    assets = []
    
    # model_data.py'daki 'A' değerlerinin maksimumunu bulalım (Normalizasyon için)
    # Varsayım: A değeri 'Sağlık Puanı'dır ve yüksek olması iyidir.
    max_health_raw = max(model_data.A.values()) if model_data.A else 1

    for i in model_data.I:
        # Veri güvenliği: Sözlükte anahtar yoksa varsayılan değer ata
        raw_health = model_data.A.get(i, 0)
        
        # UI için 0-100 arasına normalize edilmiş sağlık skoru
        health_ui = round((raw_health / max_health_raw) * 100, 1)
        
        # Risk Durumu: Sağlık skoru düşükse risk yüksektir.
        # Basit bir kural seti: <50 Yüksek, 50-75 Orta, >75 Düşük
        if health_ui < 50:
            risk_label = "Yüksek"
        elif health_ui < 75:
            risk_label = "Orta"
        else:
            risk_label = "Düşük"

        # Varlık Tipi (Yatırım/Bakım)
        is_investment = model_data.Y_B.get(i, 0) == 1
        operation_type = "Yatırım" if is_investment else "Bakım"

        asset = {
            "id": i,
            "talep_no": str(model_data.TALEP_NO.get(i, "N/A")),
            "saidi": model_data.SAIDI.get(i, 0.0),
            "saifi": model_data.SAIFI.get(i, 0.0),
            "cost": model_data.C.get(i, 0),       # Maliyet
            "group": model_data.G.get(i, "Genel"), # Trafo, Kesici vb.
            "category_public": model_data.K.get(i, 0) == 1, # Kamu/Özel
            "raw_health": raw_health,
            "health_ui": health_ui,
            "risk_label": risk_label,
            "operation_type": operation_type
        }
        assets.append(asset)
    
    return assets

# ------------------------------------------------------------------------------
# ROTALAR (ROUTES)
# ------------------------------------------------------------------------------

@app.route("/")
def index():
    # Tüm varlıkları çek
    assets = get_all_assets()
    
    # Dashboard KPI Hesaplamaları
    total_assets = len(assets)
    high_risk_count = sum(1 for a in assets if a["risk_label"] == "Yüksek")
    avg_health = sum(a["health_ui"] for a in assets) / total_assets if total_assets > 0 else 0
    budget_allocated = model_data.B

    kpi = {
        "total_assets": total_assets,
        "high_risk_count": high_risk_count,
        "avg_health": round(avg_health, 1),
        "budget": budget_allocated
    }

    # Frontend'e veriyi JSON string olarak da gömelim (hızlı rendering için)
    return render_template("index.html", assets=assets, kpi=kpi)

@app.route("/api/optimize", methods=["GET", "POST"])
def run_optimization():
    """
    MCDA (Çok Kriterli Karar Verme) tabanlı basit bir optimizasyon.
    Amaç: Bütçe kısıtı altında 'Fayda/Risk İyileştirme' skorunu maksimize etmek.
    """
    try:
        assets = get_all_assets()
        budget = model_data.B
        
        # Ağırlıklar
        w1 = model_data.w1  # SAIDI etkisi
        w2 = model_data.w2  # SAIFI etkisi
        w3 = model_data.w3  # Maliyet (veya diğer faktör)
        w4 = model_data.w4  # Sağlık/Risk etkisi

        # Normalizasyon için maksimum değerleri bul (Sıfıra bölme hatasından kaçın)
        max_saidi = max((a["saidi"] for a in assets), default=1)
        max_saifi = max((a["saifi"] for a in assets), default=1)
        # Sağlıkta 'iyileştirme potansiyeli'ne bakıyoruz. Düşük sağlık = Yüksek puan.
        # raw_health max değeri zaten get_all_assets içinde kullanıldı ama burada gerekirse tekrar bakılabilir.

        scored_assets = []
        for a in assets:
            # SKORLAMA MANTIĞI:
            # SAIDI ve SAIFI yüksekse -> Müdahale önceliği yüksek
            # Sağlık düşükse -> Müdahale önceliği yüksek
            
            norm_saidi = a["saidi"] / max_saidi if max_saidi > 0 else 0
            norm_saifi = a["saifi"] / max_saifi if max_saifi > 0 else 0
            
            # Sağlık ne kadar kötüyse (100 - health_ui), skor o kadar artmalı
            norm_health_risk = (100 - a["health_ui"]) / 100.0

            # Bileşik Skor (Weighted Score)
            # Not: Maliyet genellikle "Fayda/Maliyet" oranında paydada kullanılır, 
            # ancak burada model_data'daki w3 ağırlığına sadık kalmak için skora ekliyorum.
            # w3'ün negatif veya pozitif etkisi model tasarımına bağlıdır. 
            # Burada 'Yatırım Önceliği' puanı hesaplıyoruz.
            
            priority_score = (w1 * norm_saidi) + (w2 * norm_saifi) + (w4 * norm_health_risk)
            
            # Veriye ekle
            a["priority_score"] = priority_score
            scored_assets.append(a)

        # Greedy Yaklaşım: (Skor / Maliyet) oranına göre sırala (Bang for buck)
        # Maliyeti 0 olanlar için sonsuz öncelik vermemek adına maliyete küçük epsilon eklenir veya min 1 alınır.
        scored_assets.sort(key=lambda x: x["priority_score"] / max(x["cost"], 0.001), reverse=True)

        selected = []
        used_budget = 0.0
        total_objective_val = 0.0

        for item in scored_assets:
            cost = item["cost"]
            if used_budget + cost <= budget:
                selected.append({
                    "talep_no": item["talep_no"],
                    "tur": item["operation_type"],
                    "grup": item["group"],
                    "kurum": "Kamu" if item["category_public"] else "Özel",
                    "maliyet": cost,
                    "skor": round(item["priority_score"], 4)
                })
                used_budget += cost
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
        print(f"Optimizasyon Hatası: {e}")
        return jsonify({"status": "Error", "error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)