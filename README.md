# odoo-mcp-chatgpt

MCP server สำหรับ Odoo ที่ให้ **ChatGPT / Codex** เข้าถึง Odoo ที่อยู่ในวงภายใน
ผ่าน [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)

**Odoo ไม่ต้อง public ไม่ต้องเปิด inbound port** — ทั้ง MCP server และ tunnel-client
รันอยู่ในวงเดียวกับ Odoo แล้วเปิดแค่ HTTPS ขาออกไปหา OpenAI

```
                    ┌──────────── วงภายในของคุณ ────────────┐
  ChatGPT / Codex ──►│  tunnel-client ──► mcp-server ──► Odoo │
  (คลาวด์ OpenAI)  ◄═│  outbound HTTPS เท่านั้น                │
                    └───────────────────────────────────────┘
```

## ต่างจาก cf-odoo-mcp-server ยังไง

[cf-odoo-mcp-server](https://github.com/monthop-gmail/cf-odoo-mcp-server) ให้ tool
ชุดเดียวกันแต่รันบน Cloudflare Workers ซึ่ง **วิ่งเข้า Odoo ที่ไม่ public ไม่ได้**
repo นี้จึงมีไว้สำหรับเคสนั้นโดยเฉพาะ

| | cf-odoo-mcp-server | **odoo-mcp-chatgpt** |
| --- | --- | --- |
| Odoo ต้อง public | ใช่ | **ไม่ต้อง** |
| inbound port | ผ่าน Cloudflare | **ไม่ต้องเปิดเลย** |
| ที่รัน | Cloudflare edge | Docker ข้าง Odoo |
| client หลัก | Claude Code | **ChatGPT / Codex** |
| ภาษา | TypeScript | Python |

พฤติกรรมของ tool ตั้งใจให้เหมือนกันทั้งสอง repo — [NOTES.md](NOTES.md) ของที่นั่น
ใช้อ้างอิงกับที่นี่ได้

## ไม่มี Odoo ให้ทดสอบ? มีให้ในรีโปแล้ว

`odoo-test/` มี Odoo 19 **Community** พร้อมสคริปต์ตั้งค่าให้ครบ ใช้ลองทั้งเส้นทาง
ได้โดยไม่ต้องมี Odoo ของจริง

```bash
cd odoo-test
docker compose up -d
./setup.sh          # สร้าง db + demo data + bot user สิทธิ์ต่ำ
```

สคริปต์จะพิมพ์บรรทัด `ODOO_NETWORK=` กับ `ODOO_SERVERS=` ให้คัดลอกไปใส่ `.env`
ของรีโป รันซ้ำได้ ถ้ามีของอยู่แล้วจะไม่สร้างซ้ำ (`--reset` ถ้าอยากล้างเริ่มใหม่)

bot ที่สร้างให้มีแค่ `base.group_user` + `base.group_partner_manager`
**ไม่ใช่ admin** ตรงกับที่แนะนำในหัวข้อความปลอดภัย — `odoo_get_models` จึงเรียก
ไม่ได้โดยตั้งใจ

Odoo ตัวนี้ผูก `127.0.0.1:8069` เท่านั้น (หน้าเว็บ: admin / admin) ส่วน
mcp-server เรียกผ่าน docker network ด้วยชื่อ container ไม่ได้ใช้พอร์ตนั้น

## ต้องมีอะไรบ้าง

- Docker + Docker Compose
- Odoo ที่ container นี้เรียกถึงได้ (รองรับทั้ง **Community** และ **Enterprise** พร้อมกัน)
- tunnel id + API key จาก [Platform settings](https://platform.openai.com/) ของ OpenAI
  — **หนึ่ง tunnel ต่อได้หนึ่ง MCP server** ถ้ามีหลายตัวต้องสร้างหลาย tunnel

## เริ่มใช้

```bash
cp .env.example .env      # แล้วกรอกค่า
docker compose up -d --build
```

ดูว่าท่อต่อติดไหม

```bash
docker logs odoo-mcp-chatgpt-tunnel | grep -E 'started|session initialized'
```

ต้องเห็น `mcp session initialized` และ `🟢 tunnel-client started`

ทดสอบ MCP server ตรง ๆ โดยไม่ผ่านท่อ

```bash
curl -s -X POST http://127.0.0.1:8100/mcp \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -H "authorization: Bearer $MCP_AUTH_TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

ต่อใน ChatGPT: **Settings → Apps & Connectors → Developer mode → เพิ่ม app →
เลือก connection type เป็น Tunnel → เลือก tunnel ของคุณ**

ทดสอบจาก ChatGPT จริงแล้ว ถามภาษาไทยว่า *"มี contact กี่คน แยกตามประเทศ"* แล้วมัน
เลือก `odoo_read_group` มาสรุปให้เอง ตัวเลขตรงกับ Odoo ทุกบรรทัด — รายละเอียดใน
[NOTES.md](NOTES.md#ยืนยันจาก-chatgpt-จริงแล้ว)

## ต่อ Odoo หลายเครื่องพร้อมกัน

`ODOO_SERVERS` รับได้หลายเครื่องในไฟล์เดียว — agent เลือกด้วย argument `server`
ของแต่ละ tool ต่อ CE ที่ลงเองกับ Enterprise บน Odoo Online พร้อมกันได้

```json
{
  "default_server": "ce",
  "servers": {
    "ce": {"url": "http://odoo-web:8069", "db": "test19", "username": "mcp-bot", "password": "..."},
    "ee": {"url": "https://yourcompany.odoo.com", "db": "yourcompany", "username": "bot@example.com", "password": "api-key"}
  }
}
```

`odoo_read_group` รู้ความต่างของเวอร์ชันเอง — `saas~19.4` ไม่มี `read_group` แล้ว
เหลือแต่ `formatted_read_group` ส่วน `19.0` มีทั้งคู่ tool จะลองตัวใหม่ก่อนแล้วถอย

## Tools

| Tool | method ของ Odoo |
| --- | --- |
| `odoo_list_servers` | — (แสดง server ที่ตั้งค่าไว้) |
| `odoo_version` | `common.version` |
| `odoo_context` | ผู้ใช้ บริษัท timezone ภาษา |
| `odoo_get_models` | รายชื่อ model — **ต้องสิทธิ์ Access Rights** |
| `odoo_fields_get` | `fields_get` |
| `odoo_search_count` | `search_count` |
| `odoo_search_read` | `search_read` (default `limit` 50) |
| `odoo_read` | `read` |
| `odoo_read_group` | `formatted_read_group` (ถอยไป `read_group` ถ้ารุ่นเก่า) |
| `odoo_execute` | **public method** ใดก็ได้ |
| `odoo_create` | `create` แล้วอ่าน field ที่เขียนไปกลับมา |
| `odoo_write` | `write` แล้วอ่าน field ที่เขียนไปกลับมา |
| `odoo_delete` | `unlink` |

`odoo_get_models` อ่าน `ir.model` ซึ่ง Odoo สงวนให้กลุ่ม Access Rights บัญชี
สิทธิ์ต่ำตามที่แนะนำข้างล่างจะเรียกไม่ได้ อีก 12 ตัวใช้ได้ครบ

## การตั้งค่า

| ตัวแปร | ใช้ทำอะไร |
| --- | --- |
| `CONTROL_PLANE_TUNNEL_ID` `CONTROL_PLANE_API_KEY` | **จำเป็น** ของ OpenAI tunnel |
| `MCP_AUTH_TOKEN` | **จำเป็น** bearer token ที่ tunnel-client ใช้คุยกับ mcp-server |
| `ODOO_SERVERS` | JSON หนึ่งหรือหลายเครื่อง ถ้าตั้งไว้จะชนะตัวข้างล่าง |
| `ODOO_URL` `ODOO_DB` `ODOO_USERNAME` `ODOO_PASSWORD` | ทางเลือกสำรองสำหรับเครื่องเดียว |
| `ODOO_NETWORK` | docker network ของ Odoo ถ้า Odoo เป็น container ในเครื่องเดียวกัน |
| `BLOCKED_MODELS` | model ที่ทุก tool จะปฏิเสธ ลงท้าย `*` เพื่อจับแบบขึ้นต้น |
| `ALLOWED_MODELS` | ถ้าตั้งไว้ model ต้องตรงรายการนี้ด้วยจึงจะใช้ได้ |
| `MCP_BIND_ADDR` `MCP_HOST_PORT` | พอร์ตสำหรับทดสอบในเครื่อง (ค่าเริ่มต้น `127.0.0.1:8100`) |

## ให้ container เห็น Odoo

**Odoo เป็น container ในเครื่องเดียวกัน** — วิธีที่แนะนำ ตั้ง `ODOO_NETWORK` ให้ตรง
กับ network ของ Odoo แล้วเรียกด้วยชื่อ container **Odoo ไม่ต้อง expose port เลย**

```bash
docker inspect <odoo-container> --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}'
```

**Odoo รันนอก docker บนเครื่องเดียวกัน** — ใช้ `http://host.docker.internal:8069`
(compose ประกาศ `host-gateway` ให้แล้ว) แต่ Odoo ต้องไม่ผูกแค่ `127.0.0.1`

**Odoo อยู่คนละเครื่อง** — ใส่ URL ตรง ๆ ใน `ODOO_SERVERS`

## ความปลอดภัย

`MCP_AUTH_TOKEN` กั้นระหว่าง tunnel-client กับ mcp-server ถ้าไม่ตั้ง server จะเปิดโล่ง
ให้ทุกอย่างในวงเดียวกัน — ตั้งเสมอ

**อย่าใช้บัญชี admin ของ Odoo** สิทธิ์ของบัญชีคือรั้วที่เลี่ยงไม่ได้ ส่วน
`BLOCKED_MODELS` เป็นรั้วชั้นที่สองที่กันเฉพาะทางเข้านี้ ค่าที่แนะนำ

```
BLOCKED_MODELS=ir.*,res.users*,res.groups*
```

สูตรบัญชีเฉพาะที่ทดสอบแล้วอยู่ใน
[NOTES ของ cf-odoo-mcp-server](https://github.com/monthop-gmail/cf-odoo-mcp-server/blob/main/NOTES.md#ใช้บัญชีเฉพาะแทน-admin)

## บันทึกจากการทำจริง

[NOTES.md](NOTES.md) — จุดที่สะดุดตอนต่อท่อ และสิ่งที่ทดสอบไปแล้ว

## License

MIT
