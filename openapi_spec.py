import os

def get_openapi_spec():
    base_url = os.getenv('PUBLIC_BASE_URL', '').strip()
    servers = [{"url": "/", "description": "Current Server (Relative)"}]
    if base_url:
        servers.insert(0, {"url": base_url, "description": "Production Server"})

    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "Wisata Jogja - REST API",
            "version": "1.0.0",
            "description": "Layanan pemesanan tiket objek wisata di Daerah Istimewa Yogyakarta. Bagian dari ekosistem Jogja Itinerary (Interoperabilitas Lanjut)."
        },
        "servers": servers,
        "tags": [
            {"name": "Public", "description": "Endpoint publik tanpa autentikasi"},
            {"name": "Auth", "description": "Autentikasi wisatawan"},
            {"name": "Bookings", "description": "Pengelolaan pesanan tiket wisatawan"},
            {"name": "Partner", "description": "Integrasi service-to-service antar layanan (Hotel, Transport, Itinerary)"},
            {"name": "Admin", "description": "Pengelolaan destinasi dan monitoring oleh admin"},
            {"name": "Meta", "description": "Informasi kesehatan layanan dan spesifikasi OpenAPI"},
            {"name": "Integrations", "description": "Klien interoperabilitas ke Hotel & Transport"}
        ],
        "components": {
            "securitySchemes": {
                "partnerKey": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "API Key Partner (min. 24 karakter) yang dikonfigurasi melalui PARTNER_KEYS"
                },
                "userToken": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Bearer token user hasil login (/api/v1/auth/login)"
                },
                "adminToken": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Admin-Token",
                    "description": "Token statis admin (ADMIN_TOKEN)"
                }
            },
            "schemas": {
                "Error": {
                    "type": "object",
                    "required": ["error", "code"],
                    "properties": {
                        "error": {"type": "string", "example": "Wisata tidak ditemukan"},
                        "code": {"type": "string", "example": "NOT_FOUND"}
                    }
                },
                "Health": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "example": "ok"},
                        "service": {"type": "string", "example": "wisata"},
                        "version": {"type": "string", "example": "1.0.0"},
                        "time": {"type": "string", "format": "date-time", "example": "2026-11-12T09:00:00Z"}
                    }
                },
                "Region": {
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string", "example": "kota-yogyakarta"},
                        "name": {"type": "string", "example": "Kota Yogyakarta"},
                        "tagline": {"type": "string", "example": "Jantung budaya dan sejarah Jogja"},
                        "total": {"type": "integer", "example": 10}
                    }
                },
                "Destination": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "example": 1},
                        "region": {"type": "string", "example": "kota-yogyakarta"},
                        "name": {"type": "string", "example": "Keraton Yogyakarta"},
                        "description": {"type": "string", "example": "Istana resmi Kesultanan Ngayogyakarta Hadiningrat"},
                        "price_label": {"type": "string", "example": "Rp15.000"},
                        "price": {"type": "integer", "example": 15000},
                        "price_max": {"type": "integer", "example": 25000},
                        "price_weekend": {"type": "integer", "example": 20000},
                        "photos": {"type": "array", "items": {"type": "string"}},
                        "daily_quota": {"type": "integer", "example": 500}
                    }
                },
                "Availability": {
                    "type": "object",
                    "properties": {
                        "destination_id": {"type": "integer", "example": 1},
                        "date": {"type": "string", "format": "date", "example": "2026-11-20"},
                        "qty": {"type": "integer", "example": 2},
                        "available": {"type": "boolean", "example": True},
                        "remaining": {"type": "integer", "example": 490},
                        "unit_price": {"type": "integer", "example": 15000},
                        "total": {"type": "integer", "example": 30000},
                        "currency": {"type": "string", "example": "IDR"},
                        "is_weekend": {"type": "boolean", "example": False}
                    }
                },
                "Booking": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "example": "WJ-AB12CD34"},
                        "destination_id": {"type": "integer", "example": 1},
                        "destination_name": {"type": "string", "example": "Keraton Yogyakarta"},
                        "visit_date": {"type": "string", "format": "date", "example": "2026-11-20"},
                        "qty": {"type": "integer", "example": 2},
                        "unit_price": {"type": "integer", "example": 15000},
                        "total": {"type": "integer", "example": 30000},
                        "status": {"type": "string", "enum": ["PENDING", "PAID", "REFUNDED", "EXPIRED"], "example": "PAID"},
                        "source": {"type": "string", "example": "hotel"},
                        "external_ref": {"type": "string", "nullable": True, "example": "EXT-12345"},
                        "refund_amount": {"type": "integer", "example": 0},
                        "created_at": {"type": "string", "format": "date-time", "example": "2026-11-12T10:00:00"},
                        "name": {"type": "string", "example": "Budi Santoso"},
                        "email": {"type": "string", "example": "budi@example.com"},
                        "phone": {"type": "string", "example": "08123456789"}
                    }
                }
            }
        },
        "paths": {
            "/api/v1/health": {
                "get": {
                    "tags": ["Meta", "Public"],
                    "summary": "Health check layanan Wisata Jogja",
                    "responses": {
                        "200": {
                            "description": "Layanan sehat",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Health"}}}
                        }
                    }
                }
            },
            "/api/v1/openapi.json": {
                "get": {
                    "tags": ["Meta", "Public"],
                    "summary": "Spesifikasi OpenAPI 3.0.3 dalam format JSON",
                    "responses": {
                        "200": {"description": "Spesifikasi OpenAPI"}
                    }
                }
            },
            "/api/v1/auth/register": {
                "post": {
                    "tags": ["Auth", "Public"],
                    "summary": "Pendaftaran akun wisatawan baru",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["name", "email", "password"],
                                    "properties": {
                                        "name": {"type": "string", "example": "Budi Santoso"},
                                        "email": {"type": "string", "example": "budi@example.com"},
                                        "password": {"type": "string", "minLength": 8, "example": "password123"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "201": {"description": "Akun berhasil didaftarkan"},
                        "400": {"description": "Validasi gagal", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "409": {"description": "Email sudah terdaftar", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            },
            "/api/v1/auth/login": {
                "post": {
                    "tags": ["Auth", "Public"],
                    "summary": "Login wisatawan",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["email", "password"],
                                    "properties": {
                                        "email": {"type": "string", "example": "budi@example.com"},
                                        "password": {"type": "string", "example": "password123"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "Login berhasil, mengembalikan token Bearer"},
                        "401": {"description": "Kredensial salah", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "429": {"description": "Rate limited", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            },
            "/api/v1/auth/me": {
                "get": {
                    "tags": ["Auth"],
                    "summary": "Profil wisatawan yang sedang login",
                    "security": [{"userToken": []}],
                    "responses": {
                        "200": {"description": "Data profil"},
                        "401": {"description": "Belum terautentikasi", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            },
            "/api/v1/auth/logout": {
                "post": {
                    "tags": ["Auth", "Public"],
                    "summary": "Logout wisatawan",
                    "responses": {
                        "204": {"description": "Logout sukses (stateless)"}
                    }
                }
            },
            "/api/v1/regions": {
                "get": {
                    "tags": ["Public"],
                    "summary": "Daftar wilayah di DIY",
                    "responses": {
                        "200": {
                            "description": "Daftar wilayah dan jumlah destinasi",
                            "content": {"application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/Region"}}}}
                        }
                    }
                }
            },
            "/api/v1/destinations": {
                "get": {
                    "tags": ["Public"],
                    "summary": "Daftar destinasi wisata dengan filter dan paginasi opsional",
                    "parameters": [
                        {"name": "q", "in": "query", "schema": {"type": "string"}, "description": "Pencarian nama destinasi"},
                        {"name": "region", "in": "query", "schema": {"type": "string"}, "description": "Filter slug wilayah"},
                        {"name": "ids", "in": "query", "schema": {"type": "string"}, "description": "Filter daftar ID dipisah koma (maks 50)"},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 100, "maximum": 200}, "description": "Jumlah maksimal item"},
                        {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}, "description": "Offset paginasi"}
                    ],
                    "responses": {
                        "200": {
                            "description": "Daftar destinasi",
                            "headers": {
                                "X-Total-Count": {"schema": {"type": "integer"}, "description": "Total destinasi yang cocok"}
                            },
                            "content": {"application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/Destination"}}}}
                        }
                    }
                },
                "post": {
                    "tags": ["Admin"],
                    "summary": "Tambah destinasi baru (Admin)",
                    "security": [{"adminToken": []}, {"userToken": []}],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Destination"}}}
                    },
                    "responses": {
                        "201": {"description": "Destinasi berhasil dibuat"},
                        "403": {"description": "Akses ditolak", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            },
            "/api/v1/destinations/{id}": {
                "get": {
                    "tags": ["Public"],
                    "summary": "Detail destinasi wisata",
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {
                        "200": {"description": "Data destinasi", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Destination"}}}},
                        "404": {"description": "Wisata tidak ditemukan", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                },
                "put": {
                    "tags": ["Admin"],
                    "summary": "Perbarui data destinasi (Admin)",
                    "security": [{"adminToken": []}, {"userToken": []}],
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}},
                    "responses": {
                        "200": {"description": "Destinasi diperbarui"},
                        "403": {"description": "Akses ditolak", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "404": {"description": "Wisata tidak ditemukan", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                },
                "delete": {
                    "tags": ["Admin"],
                    "summary": "Hapus destinasi wisata (Admin)",
                    "security": [{"adminToken": []}, {"userToken": []}],
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {
                        "204": {"description": "Destinasi dihapus"},
                        "403": {"description": "Akses ditolak", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "409": {"description": "Ada pesanan aktif untuk destinasi ini", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            },
            "/api/v1/destinations/{id}/calendar": {
                "get": {
                    "tags": ["Public"],
                    "summary": "Kalender harga dan kuota destinasi per bulan",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}},
                        {"name": "month", "in": "query", "schema": {"type": "string", "example": "2026-11"}, "description": "Format YYYY-MM"}
                    ],
                    "responses": {
                        "200": {"description": "Kalender harian"},
                        "404": {"description": "Wisata tidak ditemukan", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            },
            "/api/v1/destinations/{id}/availability": {
                "get": {
                    "tags": ["Public", "Partner"],
                    "summary": "Cek ketersediaan kuota dan harga untuk tanggal tertentu",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}},
                        {"name": "date", "in": "query", "required": True, "schema": {"type": "string", "format": "date", "example": "2026-11-20"}},
                        {"name": "qty", "in": "query", "schema": {"type": "integer", "default": 1}},
                        {"name": "tier", "in": "query", "schema": {"type": "string", "enum": ["base", "plus"], "default": "base"}}
                    ],
                    "responses": {
                        "200": {"description": "Status ketersediaan", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Availability"}}}},
                        "400": {"description": "Parameter tanggal tidak valid", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "404": {"description": "Wisata tidak ditemukan", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            },
            "/api/v1/bookings": {
                "get": {
                    "tags": ["Bookings", "Admin"],
                    "summary": "Daftar pesanan wisatawan atau semua pesanan (Admin)",
                    "security": [{"userToken": []}, {"adminToken": []}],
                    "parameters": [
                        {"name": "email", "in": "query", "schema": {"type": "string"}},
                        {"name": "code", "in": "query", "schema": {"type": "string"}}
                    ],
                    "responses": {
                        "200": {"description": "Daftar pesanan", "content": {"application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/Booking"}}}}},
                        "401": {"description": "Login diperlukan", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                },
                "post": {
                    "tags": ["Bookings"],
                    "summary": "Buat pesanan tiket baru (Wisatawan)",
                    "security": [{"userToken": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["destination_id", "visit_date", "qty"],
                                    "properties": {
                                        "destination_id": {"type": "integer", "example": 1},
                                        "visit_date": {"type": "string", "format": "date", "example": "2026-11-20"},
                                        "qty": {"type": "integer", "minimum": 1, "maximum": 20, "example": 2},
                                        "tier": {"type": "string", "enum": ["base", "plus"], "default": "base"},
                                        "name": {"type": "string", "example": "Budi Santoso"},
                                        "email": {"type": "string", "example": "budi@example.com"},
                                        "phone": {"type": "string", "example": "08123456789"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "201": {"description": "Pesanan dibuat (status PENDING)", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Booking"}}}},
                        "400": {"description": "Validasi gagal", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "409": {"description": "Kuota tidak mencukupi", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            },
            "/api/v1/bookings/{code}": {
                "get": {
                    "tags": ["Bookings"],
                    "summary": "Detail pesanan berdasarkan kode booking",
                    "parameters": [{"name": "code", "in": "path", "required": True, "schema": {"type": "string", "example": "WJ-AB12CD34"}}],
                    "responses": {
                        "200": {"description": "Data pesanan", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Booking"}}}},
                        "404": {"description": "Booking tidak ditemukan", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                },
                "put": {
                    "tags": ["Bookings"],
                    "summary": "Ubah tanggal kunjungan pesanan",
                    "security": [{"userToken": []}, {"adminToken": []}],
                    "parameters": [{"name": "code", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["visit_date"],
                                    "properties": {
                                        "visit_date": {"type": "string", "format": "date", "example": "2026-11-22"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "Tanggal diubah (atau butuh pembayaran jika tarif naik)", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Booking"}}}},
                        "400": {"description": "Validasi gagal", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "403": {"description": "Akses ditolak", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "409": {"description": "Status tidak valid atau kuota habis", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                },
                "delete": {
                    "tags": ["Admin"],
                    "summary": "Hapus data pesanan (Admin)",
                    "security": [{"adminToken": []}],
                    "parameters": [{"name": "code", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "204": {"description": "Booking dihapus"},
                        "403": {"description": "Akses ditolak", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            },
            "/api/v1/bookings/{code}/pay": {
                "post": {
                    "tags": ["Bookings"],
                    "summary": "Simulasi pembayaran pesanan",
                    "security": [{"userToken": []}],
                    "parameters": [{"name": "code", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["method"],
                                    "properties": {
                                        "method": {"type": "string", "enum": ["qris", "va_bca", "va_bni", "va_mandiri", "gopay", "ovo", "dana"], "example": "qris"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "Pembayaran berhasil, status menjadi PAID", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Booking"}}}},
                        "400": {"description": "Metode pembayaran tidak valid", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "403": {"description": "Akses ditolak", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "410": {"description": "Waktu pembayaran habis", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            },
            "/api/v1/bookings/{code}/cancel": {
                "post": {
                    "tags": ["Bookings"],
                    "summary": "Batalkan pesanan PENDING (sebelum bayar)",
                    "security": [{"userToken": []}, {"adminToken": []}],
                    "parameters": [{"name": "code", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Pesanan dibatalkan (EXPIRED)", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Booking"}}}},
                        "409": {"description": "Bukan status PENDING", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            },
            "/api/v1/bookings/{code}/refund": {
                "post": {
                    "tags": ["Bookings"],
                    "summary": "Ajukan pengembalian dana (refund) pesanan PAID",
                    "security": [{"userToken": []}, {"adminToken": []}],
                    "parameters": [{"name": "code", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"reason": {"type": "string", "example": "Rencana perjalanan berubah"}}
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "Refund diproses", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Booking"}}}},
                        "409": {"description": "Bukan status PAID", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "422": {"description": "Refund tidak dapat diajukan (hari-H atau lampau)", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            },
            "/api/v1/partner/bookings": {
                "get": {
                    "tags": ["Partner"],
                    "summary": "Daftar pesanan milik partner",
                    "security": [{"partnerKey": []}],
                    "parameters": [
                        {"name": "external_ref", "in": "query", "schema": {"type": "string"}, "description": "Filter referensi eksternal"},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 100}},
                        {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}}
                    ],
                    "responses": {
                        "200": {
                            "description": "Daftar pesanan partner",
                            "headers": {"X-Total-Count": {"schema": {"type": "integer"}}},
                            "content": {"application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/Booking"}}}}
                        },
                        "401": {"description": "Kunci partner tidak valid", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "429": {"description": "Rate limit partner terlampaui", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                },
                "post": {
                    "tags": ["Partner"],
                    "summary": "Buat pesanan langsung dari sistem partner (Service-to-Service)",
                    "security": [{"partnerKey": []}],
                    "parameters": [
                        {"name": "Idempotency-Key", "in": "header", "schema": {"type": "string"}, "description": "Kunci idempotensi opsional"}
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["destination_id", "visit_date", "qty", "external_ref", "customer"],
                                    "properties": {
                                        "destination_id": {"type": "integer", "example": 1},
                                        "visit_date": {"type": "string", "format": "date", "example": "2026-11-20"},
                                        "qty": {"type": "integer", "minimum": 1, "maximum": 20, "example": 2},
                                        "tier": {"type": "string", "enum": ["base", "plus"], "default": "base"},
                                        "external_ref": {"type": "string", "example": "HOTEL-RES-98765"},
                                        "customer": {
                                            "type": "object",
                                            "required": ["name", "email"],
                                            "properties": {
                                                "name": {"type": "string", "example": "Jane Doe"},
                                                "email": {"type": "string", "example": "jane@example.com"},
                                                "phone": {"type": "string", "example": "08123456789"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "201": {"description": "Pesanan partner berhasil dibuat (status PAID)", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Booking"}}}},
                        "200": {"description": "Pesanan sama dikembalikan (idempotent)", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Booking"}}}},
                        "400": {"description": "Validasi gagal", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "401": {"description": "Kunci partner tidak valid", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "409": {"description": "external_ref ganda atau kuota habis", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "429": {"description": "Rate limit partner terlampaui", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            },
            "/api/v1/partner/bookings/{code}": {
                "get": {
                    "tags": ["Partner"],
                    "summary": "Detail pesanan milik partner",
                    "security": [{"partnerKey": []}],
                    "parameters": [{"name": "code", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Data pesanan", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Booking"}}}},
                        "401": {"description": "Kunci partner tidak valid", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "404": {"description": "Booking tidak ditemukan / bukan milik partner ini", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                },
                "put": {
                    "tags": ["Partner"],
                    "summary": "Ubah tanggal kunjungan pesanan partner",
                    "security": [{"partnerKey": []}],
                    "parameters": [{"name": "code", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["visit_date"],
                                    "properties": {"visit_date": {"type": "string", "format": "date", "example": "2026-11-25"}}
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "Tanggal berhasil diubah", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Booking"}}}},
                        "400": {"description": "Tanggal tidak valid", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "401": {"description": "Kunci partner tidak valid", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "404": {"description": "Booking tidak ditemukan / bukan milik partner", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "409": {"description": "Status booking tidak valid atau kuota habis", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            },
            "/api/v1/partner/bookings/{code}/refund": {
                "post": {
                    "tags": ["Partner"],
                    "summary": "Refund pesanan partner",
                    "security": [{"partnerKey": []}],
                    "parameters": [{"name": "code", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"reason": {"type": "string", "example": "Tamu hotel membatalkan perjalanan"}}
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "Refund berhasil", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Booking"}}}},
                        "401": {"description": "Kunci partner tidak valid", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "404": {"description": "Booking tidak ditemukan / bukan milik partner", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "409": {"description": "Booking sudah di-refund", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "422": {"description": "Refund tidak dapat diajukan (hari-H atau lampau)", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                    }
                }
            }
        }
    }
    return spec
