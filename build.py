#!/usr/bin/env python3
"""Los entornos 360 de MiruXR, listos para la GPU.

Por cada foto del catálogo (Poly Haven, CC0): la baja en JPG 8192×4096, arma la cadena de mipmaps y codifica cada
nivel en ASTC 4×4 sRGB con `astcenc` (ARM), empaquetado en un KTX (v1) que iOS (MTKTextureLoader) y Android
(glCompressedTexImage2D) suben TAL CUAL a la GPU: la misma nitidez 8K con 1 byte por píxel en vez de 4, y sin
decodificar en el teléfono (antes: 134 MB de golpe al decodificar + 172 MB de textura; ahora ~43 MB).

Se publica `<id>.ktx.z` (DEFLATE crudo, RFC 1951: iOS `NSData.decompressed(using: .zlib)`, Android `Inflater(true)`)
para bajar menos (15-34 MB en vez de 43) y el JPG original como respaldo para GPUs sin ASTC.

ANDROID usa ETC2 (`<id>.etc2.ktx.z`): el formato comprimido que exige todo Android con OpenGL ES 3, a la mitad del
ASTC (~21 MB de textura). En el Pixel 8 (Mali-G715) el ASTC de 8K se rechazaba y en mosaicos se dibujaba basura SIN
error; por eso cada ETC2 lleva píxeles de referencia (`MiruXR.samples`, decodificados acá del propio ETC2) que el
teléfono compara al cargarlo: si no coinciden, usa la foto.

Uso:  python3 build.py --astcenc /ruta/a/astcenc   → out/<id>.ktx.z, out/<id>.jpg y out/manifest.json
      python3 build.py --etc2                      → out/<id>.etc2.ktx.z (requiere `pip install etcpak texture2ddecoder numpy`)
"""
import argparse, hashlib, json, os, struct, subprocess, sys, tempfile, urllib.request, zlib
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

# El mismo catálogo que el núcleo (miruxr-spatial: crates/xrkit/src/environments.rs, DOWNLOADABLE).
IDS = ["fish_hoek_beach", "umhlanga_sunrise", "kiara_1_dawn", "qwantani_dusk_2",
       "misty_pines", "rogland_clear_night", "pretville_cinema", "fireplace"]
SRC = "https://dl.polyhaven.org/file/ph-assets/HDRIs/extra/Tonemapped%20JPG/{id}.jpg"

GL_COMPRESSED_SRGB8_ALPHA8_ASTC_4x4_KHR = 0x93D0
GL_COMPRESSED_RGB8_ETC2 = 0x9274
GL_RGBA = 0x1908
GL_RGB = 0x1907
SAMPLES = 16  # píxeles de referencia que el teléfono compara al cargar el ETC2
KTX1_MAGIC = bytes([0xAB, 0x4B, 0x54, 0x58, 0x20, 0x31, 0x31, 0xBB, 0x0D, 0x0A, 0x1A, 0x0A])


def download(id_, dest):
    if not os.path.exists(dest):
        print(f"  bajando {id_}…", flush=True)
        urllib.request.urlretrieve(SRC.format(id=id_), dest)
    return dest


def astc_level(astcenc, img, quality):
    """Un nivel → bloques ASTC 4×4 (sin la cabecera de 16 bytes del .astc)."""
    with tempfile.TemporaryDirectory() as d:
        png, out = os.path.join(d, "l.png"), os.path.join(d, "l.astc")
        img.save(png)
        subprocess.run([astcenc, "-cs", png, out, "4x4", quality, "-silent"], check=True)
        data = open(out, "rb").read()
    assert data[:4] == bytes([0x13, 0xAB, 0xA1, 0x5C]), "no es un .astc"
    return data[16:]


def build(astcenc, id_, cache, out, quality):
    jpg = download(id_, os.path.join(cache, f"{id_}.jpg"))
    img = Image.open(jpg).convert("RGBA")
    w, h = img.size
    print(f"  {id_}: {w}×{h}", flush=True)
    levels, lw, lh, cur = [], w, h, img
    while True:
        levels.append(astc_level(astcenc, cur, quality))
        if lw == 1 and lh == 1:
            break
        lw, lh = max(1, lw // 2), max(1, lh // 2)
        cur = img.resize((lw, lh), Image.LANCZOS)
    # KTX v1: cabecera + por nivel (tamaño u32 + datos; los bloques ASTC ya son múltiplos de 4 bytes).
    head = KTX1_MAGIC + struct.pack("<13I", 0x04030201, 0, 1, 0, GL_COMPRESSED_SRGB8_ALPHA8_ASTC_4x4_KHR, GL_RGBA,
                                     w, h, 0, 0, 1, len(levels), 0)
    ktx = os.path.join(out, f"{id_}.ktx")
    with open(ktx, "wb") as f:
        f.write(head)
        for lv in levels:
            f.write(struct.pack("<I", len(lv)))
            f.write(lv)
    raw = open(ktx, "rb").read()
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    open(ktx + ".z", "wb").write(c.compress(raw) + c.flush())
    return {"id": id_, "width": w, "height": h, "levels": len(levels), "ktx_bytes": len(raw),
            "ktx_sha256": hashlib.sha256(raw).hexdigest(), "download_bytes": os.path.getsize(ktx + ".z")}


def mip_chain(img):
    """Los niveles de la imagen (8192×4096 → 1×1), con Lanczos."""
    w, h = img.size
    levels, lw, lh, cur = [], w, h, img
    while True:
        levels.append(cur)
        if lw == 1 and lh == 1:
            return levels
        lw, lh = max(1, lw // 2), max(1, lh // 2)
        cur = img.resize((lw, lh), Image.LANCZOS)


def etc2_level(img):
    """Un nivel → bloques ETC2 RGB (8 bytes por bloque de 4×4). Un nivel más chico que un bloque se rellena repitiendo
    el borde: el bloque cubre igual sus píxeles."""
    import etcpak
    w, h = img.size
    pw, ph = (w + 3) // 4 * 4, (h + 3) // 4 * 4
    if (pw, ph) != (w, h):
        padded = Image.new("RGBA", (pw, ph))
        padded.paste(img.resize((pw, ph), Image.NEAREST))
        padded.paste(img, (0, 0))
        img = padded
    return etcpak.compress_etc2_rgb(img.convert("RGBA").tobytes(), pw, ph)


def kv_entry(key, value):
    """Un par clave/valor de KTX v1: tamaño u32 + clave + NUL + valor, con relleno a 4 bytes."""
    body = key.encode() + b"\0" + value
    return struct.pack("<I", len(body)) + body + b"\0" * ((4 - len(body) % 4) % 4)


def build_etc2(id_, cache, out):
    import numpy as np, texture2ddecoder
    jpg = download(id_, os.path.join(cache, f"{id_}.jpg"))
    img = Image.open(jpg).convert("RGBA")
    w, h = img.size
    chain = mip_chain(img)
    levels = [etc2_level(l) for l in chain]
    # Verificación con un decodificador INDEPENDIENTE (no el del codificador): el nivel 0 tiene que parecerse a la foto.
    dec = np.frombuffer(texture2ddecoder.decode_etc2(levels[0], w, h), np.uint8).reshape(h, w, 4)[..., [2, 1, 0]]
    ref = np.asarray(img)[..., :3]
    psnr = 10 * np.log10(255 ** 2 / ((dec.astype(np.float64) - ref) ** 2).mean())
    # Un archivo roto da < 20 dB; un cielo con miles de estrellas da ~34 sin diferencia visible (revisado a ojo, 11-oct).
    assert psnr > 33, f"{id_}: el ETC2 no se parece a la foto ({psnr:.1f} dB)"
    # Píxeles de referencia: lo que la GPU tiene que devolver en esos puntos del nivel 0 (u16 x, u16 y, u8 r, g, b).
    rng = np.random.default_rng(7)
    pts = [(int(x), int(y)) for x, y in zip(rng.integers(0, w, SAMPLES), rng.integers(0, h, SAMPLES))]
    samples = struct.pack("<I", len(pts)) + b"".join(struct.pack("<HHBBB", x, y, *dec[y, x]) for x, y in pts)
    kv = kv_entry("MiruXR.samples", samples)
    head = KTX1_MAGIC + struct.pack("<13I", 0x04030201, 0, 1, 0, GL_COMPRESSED_RGB8_ETC2, GL_RGB, w, h, 0, 0, 1, len(levels), len(kv))
    raw = head + kv + b"".join(struct.pack("<I", len(lv)) + lv for lv in levels)  # los bloques ETC2 ya son múltiplos de 4 bytes
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    z = os.path.join(out, f"{id_}.etc2.ktx.z")
    open(z, "wb").write(c.compress(raw) + c.flush())
    return {"etc2_levels": len(levels), "etc2_ktx_bytes": len(raw), "etc2_sha256": hashlib.sha256(raw).hexdigest(),
            "etc2_download_bytes": os.path.getsize(z), "etc2_psnr_db": round(psnr, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--astcenc")
    ap.add_argument("--etc2", action="store_true", help="solo los ETC2 (Android); suma sus datos al manifest.json")
    ap.add_argument("--quality", default="-medium")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    if a.etc2:
        path = os.path.join(out, "manifest.json")
        manifest = json.load(open(path)) if os.path.exists(path) else [{"id": i} for i in IDS]
        for entry in manifest:
            if a.only and entry["id"] not in a.only:
                continue
            entry.update(build_etc2(entry["id"], out, out))
            print(f"  ✓ {entry['id']}.etc2.ktx {entry['etc2_ktx_bytes'] / 1048576:.1f} MB, baja "
                  f"{entry['etc2_download_bytes'] / 1048576:.1f} MB, {entry['etc2_psnr_db']} dB", flush=True)
        json.dump(manifest, open(path, "w"), indent=2)
        return
    if not a.astcenc:
        ap.error("falta --astcenc (o --etc2)")
    manifest = []
    for id_ in (a.only or IDS):
        manifest.append(build(a.astcenc, id_, out, out, a.quality))
        print(f"  ✓ {id_}.ktx {manifest[-1]['ktx_bytes'] / 1048576:.1f} MB ({manifest[-1]['levels']} niveles)", flush=True)
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=2)


if __name__ == "__main__":
    sys.exit(main())
