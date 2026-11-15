"""Bản đồ nhiệt thẻ lật vẽ bằng Streamlit Custom Component v2 (HTML/CSS/JS nhúng).

Vì sao không dùng st.html: mỗi nhịp phát lại, trang chạy lại và st.html dựng lại toàn bộ DOM, nên hiệu ứng bị cắt và
cả khối bị làm mờ lúc chạy lại. Component giữ nguyên các ô giữa các lần chạy lại; JS so trạng thái mới với trạng thái
đang hiện và chỉ lật những ô đổi: ô quay quanh trục ngang tới mép (nửa đầu), đổi mặt, rồi quay tiếp xuống (nửa sau),
mỗi ô lệch nhau một chút để lật nối tiếp nhau như bảng điện tử.

Dữ liệu (màu, chữ, vị trí) do flipgrid.py tính; JS chỉ vẽ và lật, không tính số.
Component đăng ký MỘT lần ở mức module (không đăng ký trong hàm gọi nhiều lần).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from flipgrid import tiles_payload

_HTML = '<div class="fg"></div>'

_CSS = """
.fg { position: relative; width: 100%; min-height: 280px; font-family: inherit; }
.tl { position: absolute; display: block; padding: 2px; box-sizing: border-box; text-decoration: none; color: inherit; }
.tile { width: 100%; height: 100%; perspective: 700px; }
.face { width: 100%; height: 100%; box-sizing: border-box; display: flex; flex-direction: column; align-items: center;
        justify-content: center; border-radius: 6px; border: 1px solid #e3e6ea; line-height: 1.2; overflow: hidden;
        will-change: transform; }
.s { font-weight: 700; color: #0a0a0a; }
.v { font-variant-numeric: tabular-nums; color: #6b6b6b; }
.xl .s { font-size: 26px; } .xl .v { font-size: 18px; }
.lg .s { font-size: 20px; } .lg .v { font-size: 15px; }
.md2 .s { font-size: 15px; } .md2 .v { font-size: 12px; }
.sm .s { font-size: 12px; } .sm .v { font-size: 10.5px; }
.md .face { border: 2px solid #d99a1c; } .md .v { color: #92400e; font-weight: 600; }
.hi .face { border: 2px solid #c4242a; } .hi .v { color: #c4242a; font-weight: 700; }
.na .face { border-style: dashed; }
.tl:hover .face { border-color: #9aa3ad; }
"""

_JS = """
const STATE = new WeakMap()

function hash(s) {                       // số giả ngẫu nhiên cố định theo (mã, bước), để độ trễ lật ổn định
  let h = 2166136261
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) }
  return (h >>> 0) % 1000
}

function paint(e, t) {                   // vẽ nội dung một ô (không hiệu ứng)
  e.face.style.background = t.bg
  e.face.innerHTML = '<span class="s"></span><span class="v"></span>'
  e.face.firstChild.textContent = t.sym
  e.face.lastChild.textContent = t.text
  e.tile.className = 'tile ' + t.size + ' ' + t.cls
  e.tile.title = t.title
  e.cur = { text: t.text, bg: t.bg, cls: t.cls }
  e.target = e.cur
}

function sameState(a, t) { return a && a.text === t.text && a.bg === t.bg && a.cls === t.cls }

function flip(e, t, delay, half) {
  e.anim && e.anim.cancel()
  e.busy = true
  e.target = { text: t.text, bg: t.bg, cls: t.cls }
  const a = e.face.animate(
    [{ transform: 'rotateX(0deg)' }, { transform: 'rotateX(90deg)' }],
    { duration: half, delay, easing: 'ease-in', fill: 'both' })
  e.anim = a
  a.onfinish = () => {
    paint(e, t)                           // đổi mặt khi ô đang úp mép
    const b = e.face.animate(
      [{ transform: 'rotateX(-90deg)' }, { transform: 'rotateX(0deg)' }],
      { duration: half, easing: 'ease-out', fill: 'both' })
    e.anim = b
    b.onfinish = () => { e.busy = false; e.anim = null; b.cancel() }
  }
}

export default function (component) {
  const { data, parentElement } = component
  const root = parentElement.querySelector('.fg')
  if (!root || !data) return
  let st = STATE.get(parentElement)
  if (!st) { st = { tiles: new Map(), resetKey: null }; STATE.set(parentElement, st) }
  if (st.resetKey !== data.reset_key) {   // đổi phiên hoặc bộ mã: dựng lại, không lật
    root.textContent = ''
    st.tiles.clear()
    st.resetKey = data.reset_key
  }
  root.style.aspectRatio = data.width + ' / ' + data.height
  // Không tự tắt theo prefers-reduced-motion: Windows tắt "hiệu ứng động" là báo reduce ở rất nhiều máy, và hiệu ứng lật là
  // việc người dùng chủ động bật (bấm Phát). Ai không muốn thì tắt bằng công tắc "Hiệu ứng lật" (data.animate).
  const calm = data.animate === false
  const half = Math.max(80, (data.flip_ms || 450) / 2)
  const seen = new Set()
  data.tiles.forEach((t) => {
    seen.add(t.sym)
    let e = st.tiles.get(t.sym)
    const fresh = !e
    if (fresh) {
      const a = document.createElement('a')
      a.className = 'tl'
      a.target = '_self'
      a.href = data.link + '?ma=' + encodeURIComponent(t.sym)
      const tile = document.createElement('div')
      const face = document.createElement('div')
      face.className = 'face'
      tile.appendChild(face)
      a.appendChild(tile)
      root.appendChild(a)
      e = { a, tile, face, cur: null, anim: null, busy: false }
      st.tiles.set(t.sym, e)
    }
    e.a.style.left = t.x + '%'; e.a.style.top = t.y + '%'; e.a.style.width = t.w + '%'; e.a.style.height = t.h + '%'
    if (fresh || calm) { e.anim && e.anim.cancel(); e.busy = false; paint(e, t); return }
    if (sameState(e.target, t)) return    // đang hiện hoặc đang lật tới đúng trạng thái này
    if (e.busy) {                         // nhịp mới tới khi ô chưa lật xong: bỏ hiệu ứng cũ, hiện ngay trạng thái mới
      e.anim && e.anim.cancel(); e.busy = false; paint(e, t); return
    }
    flip(e, t, (hash(t.sym + data.step) % 160), half)
  })
  for (const [sym, e] of st.tiles) {
    if (!seen.has(sym)) { e.a.remove(); st.tiles.delete(sym) }
  }
}
"""

# Đăng ký một lần khi nạp module.
_FLIPGRID = st.components.v2.component("neo_flip_treemap", html=_HTML, css=_CSS, js=_JS)


def flip_treemap(cur: pd.DataFrame, layout: dict[str, tuple], *, reset_key: str, step: int, width: float = 100.0,
                 height: float = 46.0, flip_ms: int = 450, link: str = "ma", animate: bool = True,
                 key: str = "flip_treemap"):
    """Vẽ bản đồ nhiệt. `reset_key`: đổi giá trị (đổi phiên, đổi bộ mã) thì dựng lại không lật. `step`: số thứ tự bước
    (chỉ để rải độ trễ lật). `flip_ms`: thời gian một lần lật. `animate=False`: đổi ô ngay, không lật."""
    return _FLIPGRID(
        key=key,
        data={"tiles": tiles_payload(cur, layout, width, height), "width": width, "height": height,
              "reset_key": reset_key, "step": int(step), "flip_ms": int(flip_ms), "link": link, "animate": bool(animate)},
    )
