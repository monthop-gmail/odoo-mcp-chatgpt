#!/usr/bin/env bash
# ตั้ง Odoo 19 Community สำหรับทดสอบ odoo-mcp-chatgpt ให้พร้อมใช้
#
#   ./setup.sh          สร้าง db + bot user ถ้ายังไม่มี แล้วพิมพ์ค่าที่ต้องใส่ใน .env
#   ./setup.sh --reset  ลบ db เดิมทิ้งแล้วสร้างใหม่
#
# รันซ้ำได้ ถ้ามีของอยู่แล้วจะไม่สร้างซ้ำ แค่ตั้งรหัสผ่าน bot ใหม่ให้

set -eo pipefail

ODOO_URL="${ODOO_URL:-http://127.0.0.1:8069}"
DB="${DB:-test19}"
MASTER_PW="${MASTER_PW:-admin}"
ADMIN_PW="${ADMIN_PW:-admin}"
BOT_LOGIN="${BOT_LOGIN:-mcp-bot}"

rpc() {  # rpc <service> <method> <args-json>
  curl -s -m 300 -X POST "$ODOO_URL/jsonrpc" -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"id\":1,\"params\":{\"service\":\"$1\",\"method\":\"$2\",\"args\":$3}}"
}
obj() {  # obj <model> <method> <args-json> [kwargs-json]
  local kwargs="$4"
  [ -n "$kwargs" ] || kwargs='{}'
  rpc object execute_kw "[\"$DB\",2,\"$ADMIN_PW\",\"$1\",\"$2\",$3,$kwargs]"
}
result() { python3 -c 'import json,sys;d=json.load(sys.stdin);print(json.dumps(d.get("result")) if "error" not in d else "ERROR: "+str(d["error"].get("data",{}).get("message","")),file=sys.stdout)'; }

echo "==> รอ Odoo ที่ $ODOO_URL"
for i in $(seq 1 90); do
  curl -s -o /dev/null -m 3 "$ODOO_URL/web/database/selector" && break
  [ "$i" = 90 ] && { echo "Odoo ไม่ขึ้นภายใน 3 นาที — ลอง docker compose logs web"; exit 1; }
  sleep 2
done
echo "    พร้อม"

if [ "${1:-}" = "--reset" ]; then
  echo "==> ลบ database '$DB'"
  rpc db drop "[\"$MASTER_PW\",\"$DB\"]" | result
fi

echo "==> ตรวจ database"
if rpc db list '[]' | grep -q "\"$DB\""; then
  echo "    '$DB' มีอยู่แล้ว ข้าม"
else
  echo "    สร้าง '$DB' พร้อม demo data (ใช้เวลา 1-2 นาที)"
  rpc db create_database "[\"$MASTER_PW\",\"$DB\",true,\"en_US\",\"$ADMIN_PW\",\"admin\",null,null]" | result
fi

echo "==> ตรวจ bot user '$BOT_LOGIN'"
BOT_PW="$(openssl rand -hex 20)"

# ชื่อกลุ่มไม่ hardcode id เพราะ id ต่างกันได้ตามชุดโมดูลที่ลง
GID_USER="$(obj ir.model.data check_object_reference '["base","group_user"]' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"][1])')"
GID_PARTNER="$(obj ir.model.data check_object_reference '["base","group_partner_manager"]' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"][1])')"
echo "    base.group_user=$GID_USER  base.group_partner_manager=$GID_PARTNER"

EXISTING="$(obj res.users search_read "[[[\"login\",\"=\",\"$BOT_LOGIN\"]]]" '{"fields":["id"]}' \
  | python3 -c 'import json,sys;r=json.load(sys.stdin).get("result") or [];print(r[0]["id"] if r else "")')"

if [ -n "$EXISTING" ]; then
  echo "    มีอยู่แล้ว (uid $EXISTING) — ตั้งรหัสผ่านใหม่ให้"
  obj res.users write "[[$EXISTING],{\"password\":\"$BOT_PW\",\"tz\":\"Asia/Bangkok\"}]" | result >/dev/null
  BOT_UID="$EXISTING"
else
  # Odoo 19 เปลี่ยนชื่อ field จาก groups_id เป็น group_ids
  # ให้แค่ Internal User + Contact Creation ไม่ให้ base.group_system
  BOT_UID="$(obj res.users create \
    "[{\"name\":\"MCP Bot\",\"login\":\"$BOT_LOGIN\",\"password\":\"$BOT_PW\",\"tz\":\"Asia/Bangkok\",\"group_ids\":[[6,0,[$GID_USER,$GID_PARTNER]]]}]" \
    | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("result") or "")')"
  [ -n "$BOT_UID" ] || { echo "สร้าง bot ไม่สำเร็จ"; exit 1; }
  echo "    สร้างแล้ว uid $BOT_UID"
fi

echo "==> ยืนยันว่า bot ไม่ใช่ admin"
IS_ADMIN="$(obj res.users has_group "[$BOT_UID,\"base.group_system\"]" | result)"
echo "    base.group_system = $IS_ADMIN  (ต้องเป็น false)"

cat <<EOF

==> เสร็จแล้ว เอาบรรทัดนี้ไปใส่ใน .env ของ repo

ODOO_NETWORK=odoo19-mcp-test_default
ODOO_SERVERS={"default_server":"ce","servers":{"ce":{"url":"http://odoo19-mcp-test-web:8069","db":"$DB","username":"$BOT_LOGIN","password":"$BOT_PW"}}}

หน้าเว็บ Odoo: $ODOO_URL   (admin / $ADMIN_PW)
EOF
