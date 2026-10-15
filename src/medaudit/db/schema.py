"""SQLite schema definitions and DDL scripts for MedAudit BD database."""

SCHEMA_DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS brands (
    brand_id INTEGER PRIMARY KEY,
    brand_name TEXT NOT NULL,
    normalized_brand_name TEXT NOT NULL,
    manufacturer TEXT NOT NULL,
    prefix_stem TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    product_id INTEGER PRIMARY KEY,
    brand_id INTEGER NOT NULL REFERENCES brands(brand_id),
    raw_brand_name TEXT NOT NULL,
    type TEXT,
    slug TEXT,
    dosage_form TEXT,
    raw_generic TEXT,
    raw_strength TEXT,
    normalized_strength TEXT,
    release_type TEXT NOT NULL,
    manufacturer TEXT,
    raw_package_container TEXT,
    raw_package_size TEXT,
    parse_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generic_components (
    component_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    component_order INTEGER NOT NULL,
    canonical_generic TEXT NOT NULL,
    raw_component TEXT NOT NULL,
    salt TEXT,
    annotation TEXT,
    is_nti INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS strength_components (
    strength_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    component_order INTEGER NOT NULL,
    numeric_value REAL,
    canonical_unit TEXT,
    per_volume_value REAL,
    per_volume_unit TEXT,
    raw_component_strength TEXT
);

CREATE TABLE IF NOT EXISTS price_packs (
    pack_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    container_type TEXT NOT NULL,
    volume_or_weight_value REAL,
    volume_or_weight_unit TEXT,
    pack_qty INTEGER,
    unit_price_bdt REAL,
    pack_price_bdt REAL,
    normalized_unit_price_bdt REAL,
    comparison_unit TEXT NOT NULL,
    residual_band TEXT NOT NULL,
    residual_delta REAL,
    source_span TEXT
);

CREATE TABLE IF NOT EXISTS parse_anomalies (
    anomaly_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER REFERENCES products(product_id),
    module TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    raw_string TEXT,
    details TEXT
);

CREATE TABLE IF NOT EXISTS lasa_pairs (
    brand_id_a INTEGER NOT NULL REFERENCES brands(brand_id),
    brand_id_b INTEGER NOT NULL REFERENCES brands(brand_id),
    tier INTEGER NOT NULL,
    edit_similarity REAL NOT NULL,
    phonetic_match INTEGER NOT NULL,
    same_generic INTEGER NOT NULL,
    same_manufacturer INTEGER NOT NULL,
    diff_preview TEXT,
    PRIMARY KEY (brand_id_a, brand_id_b)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_brands_normalized ON brands(normalized_brand_name);
CREATE INDEX IF NOT EXISTS idx_products_brand_id ON products(brand_id);
CREATE INDEX IF NOT EXISTS idx_products_form_strength ON products(dosage_form, normalized_strength);
CREATE INDEX IF NOT EXISTS idx_generic_components_generic ON generic_components(canonical_generic);
CREATE INDEX IF NOT EXISTS idx_generic_components_product_id ON generic_components(product_id);
CREATE INDEX IF NOT EXISTS idx_strength_components_product_id ON strength_components(product_id);
CREATE INDEX IF NOT EXISTS idx_price_packs_product_id ON price_packs(product_id);
CREATE INDEX IF NOT EXISTS idx_price_packs_norm_price ON price_packs(normalized_unit_price_bdt);
"""
