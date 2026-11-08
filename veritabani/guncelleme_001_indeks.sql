-- ============================================================
-- GUNCELLEME 001: measurements tablosuna panel sorgulari icin indeks
-- Sadece DAHA ONCE kurulmus (eski) veritabani olanlar icin.
-- Yeni kurulumlarda schema.sql bu indeksi zaten olusturur.
-- Workbench'te ac -> Ctrl+Enter
-- "Error Code: 1061 Duplicate key name" hatasi = indeks zaten var, sorun yok.
-- ============================================================
USE akilli_fabrika;

ALTER TABLE measurements
  ADD KEY idx_sim_machine_end (simulation_id, machine_id, end_s);