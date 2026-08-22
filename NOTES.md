# บันทึกจากการทำจริง

สิ่งที่สะดุดระหว่างต่อ Odoo เข้ากับ ChatGPT ผ่าน OpenAI Secure MCP Tunnel และ
สิ่งที่ทดสอบไปแล้วจริง

พฤติกรรมฝั่ง Odoo ทั้งหมด — readonly field ที่ถูกทิ้งเงียบ ๆ, `read_group` ที่
หายไปใน `saas~19.4`, ความต่างระหว่าง edition — วัดไว้ที่
[NOTES ของ cf-odoo-mcp-server](https://github.com/monthop-gmail/cf-odoo-mcp-server/blob/main/NOTES.md)
แล้ว ที่นี่จดเฉพาะเรื่องท่อกับการรันใน Docker

## สารบัญ

- [ทดสอบแล้ว](#ทดสอบแล้ว) — 13 tools กับ Odoo 19 CE ผ่าน container
- [สามจุดที่สะดุดตอนต่อท่อ](#สามจุดที่สะดุดตอนต่อท่อ) — ทั้งหมดเสียเวลาไปคนละรอบ
- [ความเสี่ยงเรื่อง schema กับ OpenAI](#ความเสี่ยงเรื่อง-schema-กับ-openai) — ตรวจก่อนเขียน tool
- [ให้ container เห็น Odoo](#ให้-container-เห็น-odoo) — สามแบบ เลือกให้ถูก
- [ที่ยังไม่ได้ยืนยัน](#ที่ยังไม่ได้ยืนยัน) — ต้องมีคนกดใน ChatGPT

## ทดสอบแล้ว

ยิงครบ 13 tools ผ่าน container ไปที่ Odoo **19.0 Community** ที่ลงเอง ด้วยบัญชี
สิทธิ์ต่ำ `mcp-bot` (`base.group_user` + `base.group_partner_manager`)

| Tool | ผล |
| --- | --- |
| `odoo_version` | `19.0-20260817` |
| `odoo_list_servers` | ✅ |
| `odoo_context` | uid 8 · `MCP Bot` |
| `odoo_fields_get` | 73 fields บน `res.partner` |
| `odoo_search_count` | 40 |
| `odoo_search_read` + domain `'\|'` | ✅ |
| `odoo_read` | ✅ |
| `odoo_read_group` | `__count` + `id:max` ✅ |
| `odoo_execute` | `name_search` ✅ |
| `odoo_create` | ✅ พร้อม `fields_not_applied` |
| `odoo_write` | ✅ |
| `odoo_delete` | ✅ จำนวนกลับเท่าเดิม |
| `odoo_get_models` | ❌ ต้องสิทธิ์ Access Rights |

`odoo_get_models` ตกด้วยเหตุผลเดียวกับใน cf-odoo-mcp-server — บัญชีสิทธิ์ต่ำอ่าน
`ir.model` ไม่ได้ ไม่ใช่บั๊ก และไม่ควรแก้ด้วยการเพิ่มกลุ่ม Access Rights ให้ bot
เพราะกลุ่มนั้นจัดการ ACL ได้

`fields_not_applied` จับ `complete_name` ได้ (computed field) และข้อความไทย
(`ทดสอบ ChatGPT MCP` · `เชียงราย` → `น่าน`) ผ่าน create → write → delete ไม่เพี้ยน

รั้ว `BLOCKED_MODELS` ปฏิเสธ `ir.cron` **ตั้งแต่ก่อนวิ่งไปหา Odoo** — เห็นได้จาก
ตอนที่ Odoo ยังต่อไม่ติด tool อื่นขึ้น `Cannot reach Odoo` แต่ `ir.cron` ขึ้น
`out of scope` แสดงว่าลำดับการตรวจถูกต้อง

## สามจุดที่สะดุดตอนต่อท่อ

### `MCP_EXTRA_HEADERS` ไม่ใช่ `MCP_SERVER_AUTHORIZATION`

ตั้งชื่อผิดตอนแรก ท่อต่อ OpenAI ติด (`🟢 tunnel-client started`) แต่คุยกับ
mcp-server ไม่ได้

```
ERROR failed to connect to mcp  error: calling "initialize": Unauthorized
```

ชื่อที่ `tunnel-client` อ่านคือ **`MCP_EXTRA_HEADERS`** และรับเป็นบรรทัด header เต็ม

```yaml
- "MCP_EXTRA_HEADERS=${MCP_AUTH_TOKEN:+Authorization: Bearer ${MCP_AUTH_TOKEN}}"
```

อาการหลอกตรงที่ log บอกว่า tunnel started แล้ว ต้องดูบรรทัด
`mcp session initialized` ถึงจะรู้ว่าคุยกับ MCP server ได้จริง

### ค่า header ต้องใส่ quote ใน compose

`Authorization: Bearer xxx` มี `": "` อยู่ข้างใน YAML จึงอ่านเป็น map ไม่ใช่ string

```
services.tunnel-client.environment.[3]: unexpected type map[string]interface {}
```

ใน list form ต้องครอบ `"..."` ทั้งบรรทัด หรือเปลี่ยนไปใช้ map form

### OAuth discovery failed เป็นเรื่องปกติ

```
WARN OAuth discovery failed  error: oauth discovery invalid metadata ...
```

`tunnel-client` ลองหา `/.well-known/oauth-protected-resource` ก่อนเสมอ เราใช้
bearer token ธรรมดาจึงไม่มี endpoint นั้น **ไม่ต้องแก้** ขอแค่บรรทัดถัดไปเป็น
`mcp session initialized`

## ความเสี่ยงเรื่อง schema กับ OpenAI

repo ต้นทาง `odoo-mcp-claude` เคยแก้บั๊กนี้ **สองรอบ** (`9075284`, `d8385af`)

> add items to array schemas for **OpenAI API** compatibility

OpenAI validate schema เข้มกว่าเจ้าอื่น — array ต้องมี `items` ทุกชั้น repo นี้
ยิงเข้า ChatGPT โดยตรงจึงตรวจก่อนเขียน tool

**FastMCP ปลอดภัยโดยไม่ต้องทำอะไร** pydantic ใส่ `"items": {}` ให้เองแม้จะประกาศ
เป็น `list` เปล่า ๆ ซึ่งเป็นรูปแบบเดียวกับที่ต้องแก้มือในของเดิม

และถ้าประกาศชนิดข้างในด้วย จะได้ schema เหมือนที่ zod สร้างใน cf-odoo-mcp-server เป๊ะ

```python
Domain = Annotated[list[str | list[Any]], Field(description="...")]
```

```json
"items": { "anyOf": [ {"type": "string"}, {"items": {}, "type": "array"} ] }
```

ผลคือ domain ที่มี operator `'|'` ปนกับ list ส่งผ่านได้ ตรวจแล้วว่าใช้ได้จริง

## ให้ container เห็น Odoo

เสียเวลาไปสองรอบเพราะเลือกวิธีผิด

| Odoo อยู่ไหน | ใช้อะไร |
| --- | --- |
| **container ในเครื่องเดียวกัน** | เข้า network ของ Odoo แล้วเรียกด้วยชื่อ container |
| รันนอก docker บน host เดียวกัน | `host.docker.internal` + `extra_hosts: host-gateway` |
| คนละเครื่อง | ใส่ URL ตรง ๆ |

แบบแรกดีที่สุดและเป็นเคสจริงของ on-prem — **Odoo ไม่ต้อง expose port เลย**

สองอาการที่เจอตอนเลือกผิด

```
[Errno -2] Name or service not known   host.docker.internal ไม่มีบน Linux
                                        ถ้าไม่ประกาศ extra_hosts
[Errno 111] Connection refused          ประกาศแล้วแต่ Odoo ผูก 127.0.0.1
                                        จึงไม่รับจาก bridge
```

อาการที่สองน่าสนใจ เพราะการที่ Odoo ผูก loopback อย่างเดียวคือสิ่งที่**ถูกต้อง**
อยู่แล้ว ทางแก้จึงไม่ใช่ไปเปิด Odoo ให้กว้างขึ้น แต่ให้ MCP เข้าไปอยู่ใน network
เดียวกันแทน

## ที่ยังไม่ได้ยืนยัน

**ยังไม่ได้ทดสอบจากฝั่ง ChatGPT จริง** — ต้องมีคนเข้าไปกดเพิ่ม app ใน developer
mode แล้วเลือก tunnel ที่ยืนยันได้คือท่อ handshake กับ mcp-server สำเร็จ
(`mcp session initialized`) และ metrics ของ tunnel-client เห็น request วิ่งเข้า
`/mcp` จริง

ระหว่าง handshake เห็น response พวกนี้จาก mcp-server

```
DELETE /mcp  405 Method Not Allowed
GET    /mcp  406 Not Acceptable
```

มาจาก `stateless_http=True` ซึ่งไม่มี session ให้ปิดและไม่มี SSE stream ให้เปิด
workshop ต้นทางตั้งค่าเดียวกันและใช้งานได้ จึงน่าจะไม่เป็นปัญหา แต่ถ้า ChatGPT
ต่อไม่ได้ ให้สงสัยจุดนี้ก่อน

**หนึ่ง tunnel ต่อได้หนึ่ง MCP server** — ตอนทดสอบใช้ tunnel id ตัวเดียวกับ
workshop `mydrive-mcp-tunnel-workshop` ได้เพราะ workshop ไม่ได้รันอยู่ ถ้าจะใช้
สองอันพร้อมกันต้องสร้าง tunnel เพิ่ม
