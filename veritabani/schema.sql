-- ============================================================
-- AKILLI FABRIKA - MySQL veritabani semasi (v1)
-- Calistirma: MySQL Workbench'te dosyayi ac -> Ctrl+Shift+Enter
-- Birden fazla kez calistirmak guvenlidir (IF NOT EXISTS).
-- ============================================================

CREATE DATABASE IF NOT EXISTS akilli_fabrika
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE akilli_fabrika;

-- ------------------------------------------------------------
-- 1) Makineler
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS machines (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  machine_code  VARCHAR(20)  NOT NULL UNIQUE,   -- M1, M2, M3
  name          VARCHAR(100) NOT NULL,
  p_idle_kw     DOUBLE NULL,                    -- bosta guc (kW)
  efficiency    DOUBLE NULL,                    -- verim (0-1)
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 2) Simulasyon calismalari
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS simulations (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  simulation_code  VARCHAR(50) NOT NULL UNIQUE, -- ornek: SIM-20261024-143000
  scenario         VARCHAR(50) NULL,            -- normal / anormal
  started_at       DATETIME(3) NULL,
  ended_at         DATETIME(3) NULL
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 3) Olcumler (MQTT -> subscriber buraya yazar)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS measurements (
  id               BIGINT AUTO_INCREMENT PRIMARY KEY,
  simulation_id    INT         NOT NULL,
  machine_id       INT         NOT NULL,
  seq              INT         NOT NULL,        -- makine bazli sira numarasi
  ts               DATETIME(3) NOT NULL,        -- olcum bitis zamani
  start_s          DOUBLE NULL,                 -- simulasyon zamani (sn)
  end_s            DOUBLE NULL,
  duration_s       DOUBLE NULL,
  phase            VARCHAR(30) NULL,            -- baslangic_bosta, normal_kesme ...
  status           VARCHAR(20) NULL,            -- idle / working / stopped
  power_kw         DOUBLE NOT NULL,
  energy_kwh       DOUBLE NULL,                 -- kumulatif toplam enerji
  completed_parts  INT NULL,
  work_s           DOUBLE NULL,
  idle_s           DOUBLE NULL,
  fault_label      TINYINT NULL,                -- 0 normal, 1 arizali
  -- Ayni olcum ikinci kez yazilamasin (tekrar kayit korumasi)
  UNIQUE KEY uq_measurement (simulation_id, machine_id, seq),
  KEY idx_machine_ts (machine_id, ts),
  CONSTRAINT fk_meas_sim     FOREIGN KEY (simulation_id) REFERENCES simulations(id),
  CONSTRAINT fk_meas_machine FOREIGN KEY (machine_id)    REFERENCES machines(id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 4) Analiz pencereleri (AI ozellikleri)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analyses (
  id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
  machine_id          INT NOT NULL,
  simulation_id       INT NULL,
  window_start        DATETIME(3) NOT NULL,
  window_end          DATETIME(3) NOT NULL,
  mean_power_kw       DOUBLE NULL,
  max_power_kw        DOUBLE NULL,
  std_power_kw        DOUBLE NULL,
  production_rate     DOUBLE NULL,              -- uretim hizi
  work_idle_ratio     DOUBLE NULL,              -- calisma / bosta orani
  energy_per_part_kwh DOUBLE NULL,
  created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  KEY idx_analysis_machine (machine_id, window_end),
  CONSTRAINT fk_an_machine FOREIGN KEY (machine_id)    REFERENCES machines(id),
  CONSTRAINT fk_an_sim     FOREIGN KEY (simulation_id) REFERENCES simulations(id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 5) Model sonuclari
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_results (
  id             BIGINT AUTO_INCREMENT PRIMARY KEY,
  analysis_id    BIGINT NOT NULL,
  model_version  VARCHAR(50) NOT NULL,
  anomaly_score  DOUBLE NOT NULL,
  is_anomaly     TINYINT NOT NULL,
  created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_mr_analysis FOREIGN KEY (analysis_id) REFERENCES analyses(id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 6) Uyarilar
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  machine_id   INT NOT NULL,
  alert_type   VARCHAR(50) NOT NULL,            -- makine_durdu, veri_yok, yuksek_guc ...
  severity     VARCHAR(20) NULL,                -- info / warning / critical
  message      VARCHAR(255) NULL,
  created_at   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  resolved_at  DATETIME(3) NULL,
  KEY idx_alert_machine (machine_id, created_at),
  CONSTRAINT fk_alert_machine FOREIGN KEY (machine_id) REFERENCES machines(id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- Baslangic verisi: uc makine (makine_ayarlari.py ile ayni)
-- ------------------------------------------------------------
INSERT IGNORE INTO machines (machine_code, name, p_idle_kw, efficiency) VALUES
  ('M1', '15 Yıllık Torna', 3.2, 0.72),
  ('M2', 'Eco CNC',         1.1, 0.90),
  ('M3', 'Çift Aynalı CNC', 4.2, 0.86);
