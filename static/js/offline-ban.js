/* Bán hàng khi mất mạng.
 *
 * Store v0 (`phieu`, `anhchup`) là contract đang chạy và không được promote.
 * Store v1 giữ credential, catalog bind, receipt DRAFT/READY và checkpoint
 * riêng. I09-F1 chỉ tạo chứng từ bền; việc gửi v1 thuộc I09-F2.
 */
(function (global) {
    'use strict';

    const TEN_DB = 'fselling-offline';
    const PHIEN_BAN = 2;
    const KHO_PHIEU = 'phieu';
    const KHO_ANH_CHUP = 'anhchup';
    const KHO_CREDENTIAL_V1 = 'credential_v1';
    const KHO_CATALOG_V1 = 'catalog_v1';
    const KHO_PHIEU_V1 = 'receipt_v1';
    const KHO_META_V1 = 'meta_v1';
    const MAX_VND = 9000000000000000;
    const MAX_QUANTITY = 1000000000;
    const MAX_ITEMS = 200;
    const PREFIX_CATALOG_V1 = 'FS-OFFLINE-CATALOG-v1\n';
    const PREFIX_PHIEU_V1 = 'FS-OFFLINE-RECEIPT-v1\n';
    const OFFLINE_SEAL_MARKER_PREFIX = 'fselling.offline-seal.v1:';
    const FIELD_SEP = '\x1f';
    const RECORD_SEP = '\x1e';

    let _db = null;

    function ensureIndex(store, name, keyPath, options) {
        if (!store.indexNames.contains(name)) store.createIndex(name, keyPath, options || {});
    }

    function moDB() {
        if (_db) return Promise.resolve(_db);
        return new Promise(function (ok, that_bai) {
            let settled = false;
            const yc = indexedDB.open(TEN_DB, PHIEN_BAN);
            yc.onupgradeneeded = function () {
                const db = yc.result;
                const tx = yc.transaction;
                let store;
                if (!db.objectStoreNames.contains(KHO_PHIEU)) {
                    store = db.createObjectStore(KHO_PHIEU, { keyPath: 'offline_uuid' });
                } else {
                    store = tx.objectStore(KHO_PHIEU);
                }
                ensureIndex(store, 'shop_id', 'shop_id', { unique: false });

                if (!db.objectStoreNames.contains(KHO_ANH_CHUP)) {
                    db.createObjectStore(KHO_ANH_CHUP, { keyPath: 'khoa' });
                }

                if (!db.objectStoreNames.contains(KHO_CREDENTIAL_V1)) {
                    store = db.createObjectStore(KHO_CREDENTIAL_V1, { keyPath: 'lease_id' });
                } else {
                    store = tx.objectStore(KHO_CREDENTIAL_V1);
                }
                ensureIndex(store, 'identity_key', 'identity_key', { unique: false });
                ensureIndex(store, 'shop_id', 'shop_id', { unique: false });
                ensureIndex(store, 'status', 'status', { unique: false });

                if (!db.objectStoreNames.contains(KHO_CATALOG_V1)) {
                    store = db.createObjectStore(KHO_CATALOG_V1, { keyPath: 'lease_id' });
                } else {
                    store = tx.objectStore(KHO_CATALOG_V1);
                }
                ensureIndex(store, 'identity_key', 'identity_key', { unique: false });

                if (!db.objectStoreNames.contains(KHO_PHIEU_V1)) {
                    store = db.createObjectStore(KHO_PHIEU_V1, { keyPath: 'offline_uuid' });
                } else {
                    store = tx.objectStore(KHO_PHIEU_V1);
                }
                ensureIndex(store, 'identity_key', 'identity_key', { unique: false });
                ensureIndex(store, 'state', 'state', { unique: false });
                ensureIndex(store, 'lease_sequence', ['lease_id', 'sequence'], { unique: true });

                if (!db.objectStoreNames.contains(KHO_META_V1)) {
                    db.createObjectStore(KHO_META_V1, { keyPath: 'key' });
                }
            };
            yc.onsuccess = function () {
                if (settled) {
                    yc.result.close();
                    return;
                }
                settled = true;
                const connection = yc.result;
                _db = connection;
                connection.onversionchange = function () {
                    if (_db === connection) _db = null;
                    connection.close();
                };
                ok(_db);
            };
            yc.onerror = function () {
                if (!settled) {
                    settled = true;
                    that_bai(yc.error || new Error('Không mở được IndexedDB'));
                }
            };
            yc.onblocked = function () {
                if (!settled) {
                    settled = true;
                    that_bai(new Error('IndexedDB đang bị tab cũ chặn nâng phiên bản'));
                }
            };
        });
    }

    function giaoDich(ten_kho, che_do, viec) {
        const ds = Array.isArray(ten_kho) ? ten_kho : [ten_kho];
        return moDB().then(function (db) {
            return new Promise(function (ok, that_bai) {
                let ket_qua;
                let loi_noi_bo = null;
                let da_xong = false;
                let tx;
                try {
                    tx = db.transaction(ds, che_do);
                } catch (e) {
                    that_bai(e);
                    return;
                }
                function datKetQua(value) { ket_qua = value; }
                function huy(error) {
                    loi_noi_bo = error instanceof Error ? error : new Error(String(error));
                    try { tx.abort(); } catch (e) { /* transaction đã tự abort */ }
                }
                tx.oncomplete = function () {
                    if (da_xong) return;
                    da_xong = true;
                    ok(ket_qua);
                };
                tx.onabort = function () {
                    if (da_xong) return;
                    da_xong = true;
                    that_bai(loi_noi_bo || tx.error || new Error('IndexedDB transaction bị hủy'));
                };
                tx.onerror = function () {
                    // Chờ `abort`: chỉ completion/abort mới quyết định durable.
                };
                try {
                    viec(tx, datKetQua, huy);
                } catch (e) {
                    huy(e);
                }
            });
        });
    }

    function chay(ten_kho, che_do, viec) {
        return giaoDich(ten_kho, che_do, function (tx, datKetQua) {
            const request = viec(tx.objectStore(ten_kho));
            if (request && typeof request === 'object' && 'onsuccess' in request) {
                request.onsuccess = function () { datKetQua(request.result); };
            } else {
                datKetQua(request);
            }
        });
    }

    function banSao(value) {
        if (value === undefined) return undefined;
        if (global.structuredClone) return global.structuredClone(value);
        return JSON.parse(JSON.stringify(value));
    }

    function dangOffline() {
        return navigator.onLine === false;
    }

    function usernameHienTai() {
        try { return localStorage.getItem('username') || ''; } catch (e) { return ''; }
    }

    function pendingSealMarkersV1() {
        const markers = [];
        try {
            for (let i = 0; i < localStorage.length; i += 1) {
                const key = localStorage.key(i);
                if (!key || !key.startsWith(OFFLINE_SEAL_MARKER_PREFIX)) continue;
                const value = localStorage.getItem(key);
                let parsed;
                try { parsed = JSON.parse(value); } catch (e) { continue; }
                if (parsed && typeof parsed.username === 'string' && parsed.username
                    && typeof parsed.generation === 'string' && parsed.generation) {
                    markers.push({ key, value, username: parsed.username });
                }
            }
        } catch (e) {
            // Storage bị chặn: identity checks ở credential/receipt vẫn fail-closed.
        }
        return markers;
    }

    async function applyPendingSealsV1() {
        const markers = pendingSealMarkersV1();
        for (const marker of markers) {
            await sealIdentityV1({ username: marker.username });
            try {
                if (localStorage.getItem(marker.key) === marker.value) {
                    localStorage.removeItem(marker.key);
                }
            } catch (e) {
                // Seal đã durable; marker dư chỉ làm transaction seal idempotent lại.
            }
        }
    }

    function identityKey(shopId, userId, username, deviceId) {
        return JSON.stringify([shopId, userId, username, deviceId]);
    }

    function activeKey(shopId, username, deviceId) {
        return 'active:' + JSON.stringify([shopId, username, deviceId]);
    }

    function soNguyen(value, min, max, label) {
        if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < min || value > max) {
            throw new Error(label + ' phải là số nguyên an toàn');
        }
        return value;
    }

    function vanBanKhongCam(value, label) {
        if (typeof value !== 'string' || !value) throw new Error(label + ' không hợp lệ');
        for (const char of value) {
            const cp = char.codePointAt(0);
            if (cp <= 0x1f || (cp >= 0x7f && cp <= 0x9f) ||
                (cp >= 0xd800 && cp <= 0xdfff)) {
                throw new Error(label + ' chứa ký tự bị cấm');
            }
        }
        return value;
    }

    function chuanHoaTen(value) {
        if (typeof value !== 'string') throw new Error('product_name phải là chuỗi');
        const normalized = value.normalize('NFC');
        for (const char of normalized) {
            const cp = char.codePointAt(0);
            if (cp <= 0x1f || (cp >= 0x7f && cp <= 0x9f) ||
                (cp >= 0x200b && cp <= 0x200d) || cp === 0xfeff ||
                (cp >= 0xd800 && cp <= 0xdfff) || cp === 0x2028 || cp === 0x2029) {
                throw new Error('product_name chứa ký tự bị cấm');
            }
        }
        const result = normalized.trim().split(/\s+/u).filter(Boolean).join(' ');
        if (!result || Array.from(result).length > 300 || new TextEncoder().encode(result).length > 900) {
            throw new Error('product_name vượt giới hạn canonical');
        }
        return result;
    }

    function hex(bytes) {
        return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
    }

    async function sha256(text) {
        if (!global.crypto || !global.crypto.subtle) throw new Error('Web Crypto SHA-256 không khả dụng');
        return hex(await global.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)));
    }

    function uuidCrypto(prefix) {
        if (!global.crypto) throw new Error('Web Crypto không khả dụng');
        if (typeof global.crypto.randomUUID === 'function') return prefix + global.crypto.randomUUID();
        if (typeof global.crypto.getRandomValues !== 'function') throw new Error('Web Crypto RNG không khả dụng');
        const bytes = new Uint8Array(16);
        global.crypto.getRandomValues(bytes);
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        const h = hex(bytes);
        return prefix + `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    }

    function taoUuidV0() {
        if (global.crypto && crypto.randomUUID) return 'off-' + crypto.randomUUID();
        return 'off-' + Date.now() + '-' + Math.random().toString(16).slice(2, 10);
    }

    function taoDeviceId() {
        return uuidCrypto('dev_');
    }

    function hieuLucDen(expiresAt) {
        if (typeof expiresAt !== 'string') return false;
        const parsed = Date.parse(expiresAt.replace(' ', 'T') + 'Z');
        return Number.isFinite(parsed) && Date.now() < parsed;
    }

    function canonicalServerTime(value, label) {
        if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6}$/.test(value || '')) {
            throw new Error(label + ' không đúng canonical UTC');
        }
        if (canonicalTimeV1(value) !== value) {
            throw new Error(label + ' không đúng canonical UTC');
        }
        const parsed = Date.parse(value.replace(' ', 'T') + 'Z');
        if (!Number.isFinite(parsed)) throw new Error(label + ' ngoài miền thời gian');
        return parsed;
    }

    function validateIssued(issued, shopId, deviceId, catalogDigest) {
        if (!issued || issued.status !== 'ACTIVE' || issued.shop_id !== shopId
            || issued.device_id !== deviceId || issued.contract_version !== 1
            || issued.catalog_snapshot_digest !== catalogDigest
            || !/^[0-9a-f]{64}$/.test(issued.catalog_snapshot_digest || '')
            || !/^lse_[0-9A-HJKMNP-TV-Z]{22}$/.test(issued.lease_id || '')
            || !/^[A-Za-z0-9_-]{43}$/.test(issued.lease_token || '')) {
            return false;
        }
        try {
            soNguyen(issued.user_id, 1, MAX_QUANTITY, 'user_id');
            soNguyen(issued.catalog_version, 0, MAX_QUANTITY, 'catalog_version');
            soNguyen(issued.state_version, 0, MAX_QUANTITY, 'state_version');
            vanBanKhongCam(issued.server_anchor_id, 'server_anchor_id');
            canonicalServerTime(issued.server_time_utc, 'server_time_utc');
            const anchor = canonicalServerTime(issued.anchor_server_time_utc, 'anchor_server_time_utc');
            const issuedAt = canonicalServerTime(issued.issued_at, 'issued_at');
            const expiresAt = canonicalServerTime(issued.expires_at, 'expires_at');
            return anchor === issuedAt && expiresAt > issuedAt;
        } catch (e) {
            return false;
        }
    }

    function performanceState() {
        if (!global.performance || typeof global.performance.now !== 'function') {
            throw new Error('Performance monotonic clock không khả dụng');
        }
        const now = global.performance.now();
        const epoch = global.performance.timeOrigin;
        if (!Number.isFinite(now) || !Number.isFinite(epoch)) {
            throw new Error('Performance monotonic clock không hợp lệ');
        }
        return { epoch: String(epoch), now: Math.floor(now) };
    }

    function themMilliGiay(anchor, deltaMs) {
        const match = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})\.(\d{6})$/.exec(anchor || '');
        if (!match) throw new Error('Server anchor không đúng canonical UTC');
        const fraction = match[7];
        const base = Date.UTC(
            Number(match[1]), Number(match[2]) - 1, Number(match[3]),
            Number(match[4]), Number(match[5]), Number(match[6]), Number(fraction.slice(0, 3))
        );
        const d = new Date(base + deltaMs);
        if (!Number.isFinite(d.getTime())) throw new Error('Client time vượt miền biểu diễn');
        return d.toISOString().slice(0, 23).replace('T', ' ') + fraction.slice(3);
    }

    function canonicalTimeV1(value) {
        if (typeof value !== 'string') throw new Error('sold_at_client_utc phải là chuỗi');
        const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|z|[+-]\d{2}:?\d{2})?$/.exec(value.trim());
        if (!m) throw new Error('sold_at_client_utc không phải ISO-8601');
        const fraction = (m[7] || '').padEnd(6, '0');
        const year = Number(m[1]), month = Number(m[2]), day = Number(m[3]);
        const hour = Number(m[4]), minute = Number(m[5]), second = Number(m[6]);
        const millisecond = Number(fraction.slice(0, 3));
        const naive = new Date(0);
        naive.setUTCFullYear(year, month - 1, day);
        naive.setUTCHours(hour, minute, second, millisecond);
        if (naive.getUTCFullYear() !== year || naive.getUTCMonth() !== month - 1
            || naive.getUTCDate() !== day || naive.getUTCHours() !== hour
            || naive.getUTCMinutes() !== minute || naive.getUTCSeconds() !== second) {
            throw new Error('sold_at_client_utc không phải ISO-8601');
        }
        let millis = naive.getTime();
        const zone = m[8];
        if (zone && !/^[Zz]$/.test(zone)) {
            const sign = zone[0] === '+' ? 1 : -1;
            const digits = zone.slice(1).replace(':', '');
            const zoneHour = Number(digits.slice(0, 2));
            const zoneMinute = Number(digits.slice(2));
            if (zoneHour > 23 || zoneMinute > 59) {
                throw new Error('sold_at_client_utc không phải ISO-8601');
            }
            millis -= sign * (zoneHour * 60 + zoneMinute) * 60000;
        }
        const d = new Date(millis);
        if (!Number.isFinite(d.getTime())) throw new Error('sold_at_client_utc ngoài miền biểu diễn');
        return d.toISOString().slice(0, 23).replace('T', ' ') + fraction.slice(3);
    }

    function compareBytes(a, b) {
        const aa = new TextEncoder().encode(a);
        const bb = new TextEncoder().encode(b);
        const n = Math.min(aa.length, bb.length);
        for (let i = 0; i < n; i += 1) {
            if (aa[i] !== bb[i]) return aa[i] - bb[i];
        }
        return aa.length - bb.length;
    }

    function chuanHoaItems(items, catalogRows) {
        if (!Array.isArray(items) || items.length < 1 || items.length > MAX_ITEMS) {
            throw new Error('Phiếu v1 phải có 1..200 dòng');
        }
        const catalogById = new Map((catalogRows || []).map(row => [row.id, row]));
        let total = 0;
        const result = items.map(function (item) {
            if (!item || typeof item !== 'object') throw new Error('Dòng hàng không hợp lệ');
            const productId = soNguyen(item.product_id, 1, MAX_QUANTITY, 'product_id');
            const priceSource = Object.prototype.hasOwnProperty.call(item, 'unit_price_vnd')
                ? item.unit_price_vnd : item.price;
            const unitPrice = soNguyen(priceSource, 0, MAX_VND, 'unit_price_vnd');
            const quantity = soNguyen(item.quantity, 1, MAX_QUANTITY, 'quantity');
            const name = chuanHoaTen(item.product_name);
            const catalog = catalogById.get(productId);
            if (!catalog || catalog.is_active !== true || catalog.name !== name || catalog.price_vnd !== unitPrice) {
                throw new Error('Dòng hàng không khớp catalog snapshot của lease');
            }
            const line = unitPrice * quantity;
            if (!Number.isSafeInteger(line) || line > MAX_VND || total > MAX_VND - line) {
                throw new Error('Tổng tiền v1 vượt miền INTEGER VND');
            }
            total += line;
            return { product_id: productId, product_name: name, unit_price_vnd: unitPrice, quantity };
        });
        result.sort(function (a, b) {
            return a.product_id - b.product_id
                || compareBytes(a.product_name, b.product_name)
                || a.unit_price_vnd - b.unit_price_vnd
                || a.quantity - b.quantity;
        });
        return { items: result, total };
    }

    async function catalogSnapshot(products) {
        if (!Array.isArray(products)) throw new Error('Catalog phải là mảng');
        const rows = products.map(function (product) {
            if (!product || typeof product !== 'object') throw new Error('Catalog product không hợp lệ');
            return {
                id: soNguyen(product.id, 1, MAX_QUANTITY, 'catalog product_id'),
                is_active: Boolean(product.is_active),
                name: chuanHoaTen(product.name),
                price_vnd: soNguyen(product.price, 0, MAX_VND, 'catalog price_vnd'),
                track_batches: Boolean(product.track_batches)
            };
        });
        rows.sort((a, b) => a.id - b.id);
        const canonicalJson = JSON.stringify(rows);
        return {
            rows,
            canonical_json: canonicalJson,
            digest: await sha256(PREFIX_CATALOG_V1 + canonicalJson)
        };
    }

    function publicCredential(credential) {
        if (!credential) return null;
        const copy = banSao(credential);
        delete copy.lease_token;
        delete copy.identity_key;
        return copy;
    }

    function docTatCaStore(storeName) {
        return chay(storeName, 'readonly', kho => kho.getAll()).then(ds => ds || []);
    }

    async function layDeviceId() {
        const key = 'device_id_v1';
        return giaoDich(KHO_META_V1, 'readwrite', function (tx, datKetQua, huy) {
            const store = tx.objectStore(KHO_META_V1);
            const request = store.get(key);
            request.onsuccess = function () {
                const existing = request.result;
                if (existing && typeof existing.value === 'string'
                    && existing.value.length >= 1 && existing.value.length <= 128) {
                    datKetQua(existing.value);
                    return;
                }
                try {
                    const value = taoDeviceId();
                    store.put({ key, value });
                    datKetQua(value);
                } catch (e) { huy(e); }
            };
        });
    }

    function credentialUsable(credential, options) {
        return Boolean(
            credential
            && credential.contract_version === 1
            && credential.status === 'ACTIVE'
            && credential.sealed !== true
            && credential.shop_id === options.shop_id
            && credential.username === options.username
            && credential.device_id === options.device_id
            && (!options.user_id || credential.user_id === options.user_id)
            && hieuLucDen(credential.expires_at)
        );
    }

    async function prepareV1(options) {
        const shopId = soNguyen(Number(options && options.shop_id), 1, MAX_QUANTITY, 'shop_id');
        const username = vanBanKhongCam(String(options && options.username || ''), 'username');
        if (dangOffline() || usernameHienTai() !== username) return null;
        await applyPendingSealsV1();
        const deviceId = await layDeviceId();
        const pointerKey = activeKey(shopId, username, deviceId);
        // Online catalog đang được chuẩn bị thay thế capability hiện hành.
        // Xóa pointer trước mọi digest/issue async: nếu tab crash, SHA/issue hay
        // quota fail thì fallback v0, không dùng nhầm lease của catalog cũ.
        await chay(KHO_META_V1, 'readwrite', kho => kho.delete(pointerKey));
        const snapshot = await catalogSnapshot(options.products);
        const credentials = await docTatCaStore(KHO_CREDENTIAL_V1);
        const catalogs = await docTatCaStore(KHO_CATALOG_V1);
        const catalogByLease = new Map(catalogs.map(row => [row.lease_id, row]));
        let credential = credentials
            .filter(row => row.shop_id === shopId && row.username === username && row.device_id === deviceId)
            .filter(row => row.status === 'ACTIVE' && row.sealed !== true && hieuLucDen(row.expires_at))
            .filter(row => row.catalog_snapshot_digest === snapshot.digest)
            .filter(row => catalogByLease.get(row.lease_id)?.catalog_snapshot_digest === snapshot.digest)
            .sort((a, b) => String(b.saved_at || b.issued_at).localeCompare(String(a.saved_at || a.issued_at))
                || String(b.lease_id).localeCompare(String(a.lease_id)))[0] || null;

        if (credential) {
            const catalog = {
                lease_id: credential.lease_id,
                identity_key: credential.identity_key,
                shop_id: shopId,
                user_id: credential.user_id,
                username,
                device_id: deviceId,
                catalog_version: credential.catalog_version,
                catalog_snapshot_digest: snapshot.digest,
                saved_at: new Date().toISOString(),
                rows: snapshot.rows
            };
            await giaoDich([KHO_CREDENTIAL_V1, KHO_CATALOG_V1, KHO_META_V1], 'readwrite', function (tx) {
                tx.objectStore(KHO_CREDENTIAL_V1).put(credential);
                tx.objectStore(KHO_CATALOG_V1).put(catalog);
                tx.objectStore(KHO_META_V1).put({
                    key: pointerKey,
                    lease_id: credential.lease_id,
                    identity_key: credential.identity_key
                });
            });
            await finalizeDraftsV1({ shop_id: shopId, username, user_id: credential.user_id });
            return publicCredential(credential);
        }

        if (typeof global.apiCall !== 'function') return null;
        let issued;
        try {
            issued = await global.apiCall('/offline/leases', 'POST', {
                shop_id: shopId,
                device_id: deviceId
            });
        } catch (e) {
            await chay(KHO_META_V1, 'readwrite', kho => kho.delete(pointerKey));
            return null;
        }
        if (!validateIssued(issued, shopId, deviceId, snapshot.digest)) {
            await chay(KHO_META_V1, 'readwrite', kho => kho.delete(pointerKey));
            return null;
        }
        const userId = soNguyen(issued.user_id, 1, MAX_QUANTITY, 'user_id');
        const key = identityKey(shopId, userId, username, deviceId);
        credential = {
            ...banSao(issued),
            identity_key: key,
            username,
            sealed: false,
            local_state: 'ACTIVE',
            saved_at: new Date().toISOString()
        };
        const catalog = {
            lease_id: issued.lease_id,
            identity_key: key,
            shop_id: shopId,
            user_id: userId,
            username,
            device_id: deviceId,
            catalog_version: issued.catalog_version,
            catalog_snapshot_digest: snapshot.digest,
            saved_at: new Date().toISOString(),
            rows: snapshot.rows
        };
        const perf = performanceState();
        await giaoDich([KHO_CREDENTIAL_V1, KHO_CATALOG_V1, KHO_META_V1], 'readwrite', function (tx) {
            tx.objectStore(KHO_CREDENTIAL_V1).add(credential);
            tx.objectStore(KHO_CATALOG_V1).add(catalog);
            tx.objectStore(KHO_META_V1).put({
                key: 'clock:' + issued.lease_id,
                lease_id: issued.lease_id,
                epoch: perf.epoch,
                epoch_base_perf_ms: perf.now,
                epoch_base_cumulative_ms: 0,
                cumulative_ms: 0,
                monotonic_valid: true
            });
            tx.objectStore(KHO_META_V1).put({
                key: pointerKey,
                lease_id: issued.lease_id,
                identity_key: key
            });
        });
        return publicCredential(credential);
    }

    async function usableV1(options) {
        const username = String(options.username || '');
        if (!username || usernameHienTai() !== username) return null;
        await applyPendingSealsV1();
        const deviceId = await layDeviceId();
        const pointer = await chay(
            KHO_META_V1,
            'readonly',
            kho => kho.get(activeKey(options.shop_id, username, deviceId))
        );
        if (!pointer || typeof pointer.lease_id !== 'string') return null;
        const credentials = await docTatCaStore(KHO_CREDENTIAL_V1);
        const candidates = credentials
            .filter(row => row.lease_id === pointer.lease_id && row.identity_key === pointer.identity_key)
            .filter(row => credentialUsable(row, {
                shop_id: options.shop_id,
                username,
                user_id: options.user_id,
                device_id: deviceId
            }))
            .sort((a, b) => String(b.saved_at || b.issued_at).localeCompare(String(a.saved_at || a.issued_at))
                || String(b.lease_id).localeCompare(String(a.lease_id)));
        for (const credential of candidates) {
            const catalog = await chay(KHO_CATALOG_V1, 'readonly', kho => kho.get(credential.lease_id));
            if (catalog && catalog.identity_key === credential.identity_key
                && catalog.catalog_snapshot_digest === credential.catalog_snapshot_digest) {
                return { credential, catalog };
            }
        }
        return null;
    }

    function nextClock(clock, perf) {
        if (!clock) {
            return {
                epoch: perf.epoch,
                epoch_base_perf_ms: perf.now,
                epoch_base_cumulative_ms: 0,
                cumulative_ms: 0,
                monotonic_valid: true
            };
        }
        let next = { ...clock };
        if (clock.epoch !== perf.epoch || perf.now < clock.epoch_base_perf_ms) {
            next.epoch = perf.epoch;
            next.epoch_base_perf_ms = perf.now;
            next.epoch_base_cumulative_ms = clock.cumulative_ms;
            next.monotonic_valid = false;
            return next;
        }
        const candidate = clock.epoch_base_cumulative_ms + (perf.now - clock.epoch_base_perf_ms);
        next.cumulative_ms = Math.max(clock.cumulative_ms, candidate);
        next.monotonic_valid = clock.monotonic_valid === true;
        return next;
    }

    function fingerprintInput(receipt) {
        return {
            shop_id: receipt.shop_id,
            sold_at_client_utc: receipt.sold_at_client_utc,
            client_monotonic_ms: receipt.client_monotonic_ms,
            monotonic_valid: receipt.monotonic_valid,
            server_anchor_id: receipt.server_anchor_id,
            lease_id: receipt.lease_id,
            device_id: receipt.device_id,
            offline_session_id: receipt.offline_session_id,
            sequence: receipt.sequence,
            offline_uuid: receipt.offline_uuid,
            catalog_version: receipt.catalog_version,
            catalog_snapshot_digest: receipt.catalog_snapshot_digest,
            items: receipt.items,
            cash_tendered: receipt.cash_tendered
        };
    }

    function localCreationIntentV1(credential, normalized, tendered) {
        return JSON.stringify({
            contract_version: 1,
            identity_key: credential.identity_key,
            username: credential.username,
            user_id: credential.user_id,
            shop_id: credential.shop_id,
            lease_id: credential.lease_id,
            device_id: credential.device_id,
            offline_session_id: credential.lease_id,
            server_anchor_id: credential.server_anchor_id,
            anchor_server_time_utc: credential.anchor_server_time_utc,
            issued_at: credential.issued_at,
            expires_at: credential.expires_at,
            catalog_version: credential.catalog_version,
            catalog_snapshot_digest: credential.catalog_snapshot_digest,
            payment_method: 'CASH',
            cash_tendered: tendered,
            total_vnd: normalized.total,
            items: normalized.items
        });
    }

    async function fingerprintV1(input) {
        const shopId = soNguyen(input.shop_id, 1, MAX_QUANTITY, 'shop_id');
        const sequence = soNguyen(input.sequence, 1, MAX_QUANTITY, 'sequence');
        const monotonic = soNguyen(input.client_monotonic_ms, 0, Number.MAX_SAFE_INTEGER, 'client_monotonic_ms');
        if (typeof input.monotonic_valid !== 'boolean') throw new Error('monotonic_valid phải là boolean');
        const catalogVersion = soNguyen(input.catalog_version, 0, MAX_QUANTITY, 'catalog_version');
        const tendered = soNguyen(input.cash_tendered, 0, MAX_VND, 'cash_tendered');
        const ids = ['lease_id', 'device_id', 'offline_session_id', 'offline_uuid', 'server_anchor_id'];
        ids.forEach(name => vanBanKhongCam(input[name], name));
        if (!/^[0-9a-f]{64}$/.test(input.catalog_snapshot_digest || '')) {
            // Known-vector server test predates the production digest shape and
            // deliberately uses `sha256:deadbeef`; canonical bytes still bind it.
            vanBanKhongCam(input.catalog_snapshot_digest, 'catalog_snapshot_digest');
        }
        const normalized = chuanHoaItems(input.items, input.items.map(row => ({
            id: row.product_id,
            name: chuanHoaTen(row.product_name),
            price_vnd: row.unit_price_vnd,
            is_active: true
        })));
        const soldAt = canonicalTimeV1(input.sold_at_client_utc);
        const lines = [
            PREFIX_PHIEU_V1 + [shopId, 1, input.lease_id, input.device_id,
                input.offline_session_id, sequence, input.offline_uuid].join(FIELD_SEP),
            [soldAt, monotonic, input.monotonic_valid ? 1 : 0, input.server_anchor_id].join(FIELD_SEP),
            [catalogVersion, input.catalog_snapshot_digest].join(FIELD_SEP),
            ['CASH', tendered, normalized.total, normalized.items.length].join(FIELD_SEP),
            normalized.items.map(row => [row.product_id, row.product_name,
                row.unit_price_vnd, row.quantity].join(FIELD_SEP)).join(RECORD_SEP)
        ];
        const canonical = lines.join('\n') + '\n';
        return {
            digest: 'fsofr1:' + await sha256(canonical),
            canonical_bytes: new TextEncoder().encode(canonical),
            sold_at_client_utc: soldAt,
            items: normalized.items,
            total_vnd: normalized.total
        };
    }

    function allocateDraftV1(context, normalized, tendered, creationKey) {
        const credential = context.credential;
        const clockKey = 'clock:' + credential.lease_id;
        const sequenceKey = 'sequence:' + credential.lease_id;
        return giaoDich(
            [KHO_CREDENTIAL_V1, KHO_CATALOG_V1, KHO_META_V1, KHO_PHIEU_V1],
            'readwrite',
            function (tx, datKetQua, huy) {
                const credentials = tx.objectStore(KHO_CREDENTIAL_V1);
                const catalogs = tx.objectStore(KHO_CATALOG_V1);
                const meta = tx.objectStore(KHO_META_V1);
                const receipts = tx.objectStore(KHO_PHIEU_V1);
                const credentialRequest = credentials.get(credential.lease_id);
                credentialRequest.onsuccess = function () {
                    const fresh = credentialRequest.result;
                    if (!credentialUsable(fresh, {
                        shop_id: credential.shop_id,
                        username: credential.username,
                        user_id: credential.user_id,
                        device_id: credential.device_id
                    }) || usernameHienTai() !== fresh.username) {
                        huy(new Error('Credential v1 không còn ACTIVE cho identity hiện tại'));
                        return;
                    }
                    const catalogRequest = catalogs.get(fresh.lease_id);
                    catalogRequest.onsuccess = function () {
                        const catalog = catalogRequest.result;
                        if (!catalog || catalog.identity_key !== fresh.identity_key
                            || catalog.catalog_snapshot_digest !== fresh.catalog_snapshot_digest) {
                            huy(new Error('Catalog snapshot v1 không còn bind đúng credential'));
                            return;
                        }
                        const creationIntent = localCreationIntentV1(fresh, normalized, tendered);
                        const existingRequest = receipts.getAll();
                        existingRequest.onsuccess = function () {
                            const existing = (existingRequest.result || []).find(row =>
                                row.local_creation_key === creationKey
                            );
                            if (existing) {
                                if (existing.local_creation_intent !== creationIntent) {
                                    huy(new Error('creation_key đã bind với immutable intent khác'));
                                    return;
                                }
                                datKetQua(existing);
                                return;
                            }
                            allocateNew();
                        };
                        function allocateNew() {
                            let perf;
                            let uuid;
                            try {
                                perf = performanceState();
                                uuid = uuidCrypto('off-');
                            } catch (e) {
                                huy(e);
                                return;
                            }
                            const clockRequest = meta.get(clockKey);
                            const sequenceRequest = meta.get(sequenceKey);
                            let clockDone = false, sequenceDone = false;
                            function finish() {
                                if (!clockDone || !sequenceDone) return;
                                try {
                                    const clock = nextClock(clockRequest.result, perf);
                                    clock.key = clockKey;
                                    clock.lease_id = fresh.lease_id;
                                    clock.cumulative_ms = soNguyen(
                                        clock.cumulative_ms, 0, Number.MAX_SAFE_INTEGER,
                                        'client_monotonic_ms'
                                    );
                                    const previous = sequenceRequest.result?.value || 0;
                                    const sequence = soNguyen(previous + 1, 1, MAX_QUANTITY, 'sequence');
                                    const soldAt = themMilliGiay(
                                        fresh.anchor_server_time_utc,
                                        clock.cumulative_ms
                                    );
                                    if (soldAt < fresh.issued_at || soldAt > fresh.expires_at) {
                                        throw new Error('Checkpoint v1 nằm ngoài cửa sổ ACTIVE của lease');
                                    }
                                    const draft = {
                                        offline_uuid: uuid,
                                        identity_key: fresh.identity_key,
                                        username: fresh.username,
                                        user_id: fresh.user_id,
                                        shop_id: fresh.shop_id,
                                        contract_version: 1,
                                        lease_id: fresh.lease_id,
                                        device_id: fresh.device_id,
                                        offline_session_id: fresh.lease_id,
                                        sequence,
                                        sold_at_client_utc: soldAt,
                                        client_monotonic_ms: clock.cumulative_ms,
                                        monotonic_valid: clock.monotonic_valid,
                                        server_anchor_id: fresh.server_anchor_id,
                                        catalog_version: fresh.catalog_version,
                                        catalog_snapshot_digest: fresh.catalog_snapshot_digest,
                                        items: normalized.items,
                                        cash_tendered: tendered,
                                        local_creation_key: creationKey,
                                        local_creation_intent: creationIntent,
                                        state: 'DRAFT',
                                        draft_revision: 1,
                                        client_fingerprint: null,
                                        created_at: new Date().toISOString()
                                    };
                                    meta.put(clock);
                                    meta.put({
                                        key: sequenceKey,
                                        lease_id: fresh.lease_id,
                                        value: sequence
                                    });
                                    receipts.add(draft);
                                    datKetQua(draft);
                                } catch (e) { huy(e); }
                            }
                            clockRequest.onsuccess = function () { clockDone = true; finish(); };
                            sequenceRequest.onsuccess = function () { sequenceDone = true; finish(); };
                        }
                    };
                };
            }
        );
    }

    async function finalizeReceiptV1(uuid, identity) {
        await applyPendingSealsV1();
        const draft = await chay(KHO_PHIEU_V1, 'readonly', kho => kho.get(uuid));
        if (!draft) throw new Error('Không tìm thấy DRAFT v1');
        if (draft.username !== identity.username || usernameHienTai() !== identity.username
            || (identity.shop_id && draft.shop_id !== identity.shop_id)
            || (identity.user_id && draft.user_id !== identity.user_id)) {
            throw new Error('Identity không được đọc/finalize receipt này');
        }
        if (draft.state === 'READY') return banSao(draft);
        if (draft.state !== 'DRAFT') throw new Error('Receipt v1 không ở trạng thái DRAFT');
        const inputJson = JSON.stringify(fingerprintInput(draft));
        const fingerprint = await fingerprintV1(fingerprintInput(draft));
        return giaoDich([KHO_CREDENTIAL_V1, KHO_PHIEU_V1], 'readwrite', function (tx, datKetQua, huy) {
            const store = tx.objectStore(KHO_PHIEU_V1);
            const credentials = tx.objectStore(KHO_CREDENTIAL_V1);
            const request = store.get(uuid);
            request.onsuccess = function () {
                const fresh = request.result;
                if (!fresh || fresh.state !== 'DRAFT' || fresh.draft_revision !== draft.draft_revision
                    || JSON.stringify(fingerprintInput(fresh)) !== inputJson) {
                    huy(new Error('DRAFT v1 đã đổi trong lúc tính fingerprint'));
                    return;
                }
                const credentialRequest = credentials.get(fresh.lease_id);
                credentialRequest.onsuccess = function () {
                    const credential = credentialRequest.result;
                    if (!credentialUsable(credential, {
                        shop_id: fresh.shop_id,
                        username: fresh.username,
                        user_id: fresh.user_id,
                        device_id: fresh.device_id
                    }) || credential.identity_key !== fresh.identity_key) {
                        huy(new Error('Credential v1 không còn ACTIVE để finalize'));
                        return;
                    }
                    fresh.client_fingerprint = fingerprint.digest;
                    fresh.state = 'READY';
                    fresh.ready_at = new Date().toISOString();
                    store.put(fresh);
                    datKetQua(banSao(fresh));
                };
            };
        });
    }

    async function finalizeDraftsV1(identity) {
        const username = String(identity && identity.username || '');
        if (!username || usernameHienTai() !== username) return [];
        await applyPendingSealsV1();
        const credentials = await docTatCaStore(KHO_CREDENTIAL_V1);
        const usableLeases = new Set(credentials.filter(row =>
            row.username === username
            && (!identity.shop_id || row.shop_id === identity.shop_id)
            && (!identity.user_id || row.user_id === identity.user_id)
            && credentialUsable(row, {
                shop_id: row.shop_id,
                username,
                user_id: row.user_id,
                device_id: row.device_id
            })
        ).map(row => row.lease_id));
        const drafts = (await docTatCaStore(KHO_PHIEU_V1))
            .filter(row => row.state === 'DRAFT' && row.username === username)
            .filter(row => !identity.shop_id || row.shop_id === identity.shop_id)
            .filter(row => !identity.user_id || row.user_id === identity.user_id)
            .filter(row => usableLeases.has(row.lease_id))
            .sort((a, b) => a.lease_id.localeCompare(b.lease_id) || a.sequence - b.sequence);
        const ready = [];
        for (const draft of drafts) {
            ready.push(await finalizeReceiptV1(draft.offline_uuid, identity));
        }
        return ready;
    }

    async function createReceiptV1(options) {
        if (!dangOffline()) throw new Error('Receipt v1 chỉ được tạo khi navigator.onLine === false');
        if (!options || options.payment_method !== 'cash'
            || options.voucher_code || Number(options.loyalty_points_to_use) !== 0
            || options.qr === true || options.debt === true) {
            throw new Error('Receipt v1 chỉ hỗ trợ tiền mặt, không ưu đãi/QR/nợ/điểm');
        }
        const shopId = soNguyen(Number(options.shop_id), 1, MAX_QUANTITY, 'shop_id');
        const username = vanBanKhongCam(String(options.username || ''), 'username');
        const creationKey = vanBanKhongCam(String(options.creation_key || ''), 'creation_key');
        if (creationKey.length < 8 || creationKey.length > 128) {
            throw new Error('creation_key phải dài 8..128 ký tự');
        }
        const usable = await usableV1({ shop_id: shopId, username, user_id: options.user_id });
        if (!usable) return null;
        const normalized = chuanHoaItems(options.items, usable.catalog.rows);
        const tendered = soNguyen(options.cash_tendered, 0, MAX_VND, 'cash_tendered');
        if (tendered < normalized.total) throw new Error('Tiền khách đưa chưa đủ');
        const draft = await allocateDraftV1(usable, normalized, tendered, creationKey);
        return finalizeReceiptV1(draft.offline_uuid, {
            shop_id: shopId,
            user_id: usable.credential.user_id,
            username
        });
    }

    async function listReadyV1(identity) {
        const username = String(identity && identity.username || '');
        if (!username || usernameHienTai() !== username
            || !Number.isSafeInteger(identity.shop_id)
            || !Number.isSafeInteger(identity.user_id)
            || typeof identity.lease_id !== 'string') return [];
        await applyPendingSealsV1();
        const credential = await chay(
            KHO_CREDENTIAL_V1, 'readonly', kho => kho.get(identity.lease_id)
        );
        if (!credential || !credentialUsable(credential, {
            shop_id: identity.shop_id,
            username,
            user_id: identity.user_id,
            device_id: credential.device_id
        })) return [];
        const rows = (await docTatCaStore(KHO_PHIEU_V1))
            .filter(row => row.state === 'READY' && row.username === username)
            .filter(row => row.shop_id === identity.shop_id)
            .filter(row => row.user_id === identity.user_id)
            .filter(row => row.lease_id === identity.lease_id)
            .sort((a, b) => a.lease_id.localeCompare(b.lease_id) || a.sequence - b.sequence);
        return rows.map(function (row) {
            const copy = banSao(row);
            delete copy.identity_key;
            delete copy.local_creation_key;
            delete copy.local_creation_intent;
            return copy;
        });
    }

    async function getCredentialV1(leaseId, identity) {
        const username = String(identity && identity.username || '');
        if (!username || usernameHienTai() !== username
            || !Number.isSafeInteger(identity.shop_id)
            || !Number.isSafeInteger(identity.user_id)) return null;
        await applyPendingSealsV1();
        const credential = await chay(KHO_CREDENTIAL_V1, 'readonly', kho => kho.get(leaseId));
        if (!credential || credential.username !== username || credential.sealed === true
            || credential.shop_id !== identity.shop_id
            || credential.user_id !== identity.user_id) return null;
        return banSao(credential); // seam nội bộ explicit cho F2; có raw token.
    }

    async function getCredentialForRecoveryV1(leaseId, identity) {
        const username = String(identity && identity.username || '');
        if (!username || usernameHienTai() !== username
            || !Number.isSafeInteger(identity.shop_id)
            || !Number.isSafeInteger(identity.user_id)
            || typeof leaseId !== 'string') return null;
        await applyPendingSealsV1();
        const credential = await chay(KHO_CREDENTIAL_V1, 'readonly', kho => kho.get(leaseId));
        if (!credential || credential.username !== username || credential.sealed !== true
            || credential.shop_id !== identity.shop_id
            || credential.user_id !== identity.user_id) return null;
        const hasPending = (await docTatCaStore(KHO_PHIEU_V1)).some(row =>
            (row.state === 'DRAFT' || row.state === 'READY')
            && row.identity_key === credential.identity_key
            && row.lease_id === credential.lease_id
            && row.shop_id === credential.shop_id
            && row.user_id === credential.user_id
            && row.username === credential.username
        );
        return hasPending ? banSao(credential) : null;
    }

    async function sealIdentityV1(identity) {
        const username = String(identity && identity.username || '');
        if (!username) return;
        return giaoDich(KHO_CREDENTIAL_V1, 'readwrite', function (tx) {
            const store = tx.objectStore(KHO_CREDENTIAL_V1);
            const request = store.getAll();
            request.onsuccess = function () {
                (request.result || []).filter(row => row.username === username).forEach(function (row) {
                    row.sealed = true;
                    row.local_state = 'SEALED';
                    store.put(row);
                });
            };
        });
    }

    // ---------- Contract v0 giữ nguyên ----------
    function luuPhieu(shopId, gio_hang, tien_khach_dua, ten_may) {
        const phieu = {
            offline_uuid: taoUuidV0(),
            shop_id: Number(shopId),
            sold_at: new Date().toISOString(),
            items: (gio_hang || []).map(function (m) {
                return {
                    product_id: Number(m.product_id),
                    product_name: String(m.product_name || ''),
                    unit_price: Number(m.price) || 0,
                    quantity: Number(m.quantity) || 0
                };
            }),
            cash_tendered: Number(tien_khach_dua) || 0,
            device_label: ten_may || null,
            luc_luu: Date.now(),
            loi: null
        };
        return chay(KHO_PHIEU, 'readwrite', kho => kho.put(phieu)).then(() => phieu);
    }

    async function luuPhieuTuPOS(options) {
        const v1 = await createReceiptV1(options);
        if (v1) return v1;
        return luuPhieu(
            options.shop_id,
            options.items,
            options.cash_tendered,
            options.device_label
        );
    }

    function docTatCa(shopId) {
        return docTatCaStore(KHO_PHIEU).then(ds => ds.filter(p => !shopId || Number(p.shop_id) === Number(shopId)));
    }

    function demCho(shopId) { return docTatCa(shopId).then(ds => ds.filter(p => !p.loi).length); }
    function demLoi(shopId) { return docTatCa(shopId).then(ds => ds.filter(p => !!p.loi).length); }
    function xoaPhieu(uuid) { return chay(KHO_PHIEU, 'readwrite', kho => kho.delete(uuid)); }
    function danhDauLoi(phieu, ly_do) {
        phieu.loi = String(ly_do || 'không rõ').slice(0, 300);
        return chay(KHO_PHIEU, 'readwrite', kho => kho.put(phieu));
    }

    let _dangDongBo = false;
    async function dongBo(shopId) {
        if (_dangDongBo || dangOffline()) return { da_gui: 0, loi: 0, con_lai: await demCho(shopId) };
        _dangDongBo = true;
        let da_gui = 0, loi = 0;
        try {
            const ds = (await docTatCa(shopId)).filter(p => !p.loi);
            ds.sort((a, b) => (a.luc_luu || 0) - (b.luc_luu || 0));
            for (const phieu of ds) {
                try {
                    await apiCall(`/orders/${phieu.shop_id}/offline`, 'POST', {
                        offline_uuid: phieu.offline_uuid,
                        sold_at: phieu.sold_at,
                        items: phieu.items,
                        cash_tendered: phieu.cash_tendered,
                        device_label: phieu.device_label
                    });
                    await xoaPhieu(phieu.offline_uuid);
                    da_gui += 1;
                } catch (e) {
                    const ma = Number(e && e.status);
                    if (ma >= 400 && ma < 500) {
                        await danhDauLoi(phieu, `${ma}: ${e.message || ''}`);
                        loi += 1;
                        continue;
                    }
                    break;
                }
            }
        } finally { _dangDongBo = false; }
        return { da_gui, loi, con_lai: await demCho(shopId) };
    }

    function luuAnhChupSanPham(shopId, danh_sach) {
        return chay(KHO_ANH_CHUP, 'readwrite', kho =>
            kho.put({ khoa: 'sp:' + shopId, luc: Date.now(), du_lieu: danh_sach || [] })
        );
    }
    function docAnhChupSanPham(shopId) {
        return chay(KHO_ANH_CHUP, 'readonly', kho => kho.get('sp:' + shopId))
            .then(b => b ? b.du_lieu : null);
    }

    function batTuDongBo(layShopId, khiXong) {
        async function thu() {
            const shopId = layShopId();
            if (!shopId || dangOffline()) return;
            try {
                const kq = await dongBo(shopId);
                if (khiXong) khiXong(kq);
            } catch (e) { console.warn('[OFFLINE] Đồng bộ v0 thất bại'); }
        }
        global.addEventListener('online', thu);
        setTimeout(thu, 1500);
        return thu;
    }

    global.OfflineBan = {
        dangOffline,
        // v1 F1
        prepareV1,
        createReceiptV1,
        finalizeDraftsV1,
        listReadyV1,
        getCredentialV1,
        getCredentialForRecoveryV1,
        sealIdentityV1,
        fingerprintV1,
        luuPhieuTuPOS,
        // v0 compatibility
        luuPhieu,
        docTatCa,
        demCho,
        demLoi,
        xoaPhieu,
        dongBo,
        luuAnhChupSanPham,
        docAnhChupSanPham,
        batTuDongBo
    };

    // Crash giữa transaction DRAFT và digest được khép lại khi đúng identity
    // quay lại, kể cả lúc reload đang offline. Không đọc/finalize user khác.
    setTimeout(function () {
        const username = usernameHienTai();
        if (username) {
            applyPendingSealsV1()
                .then(() => finalizeDraftsV1({ username }))
                .catch(function () {});
        }
    }, 0);
})(window);
