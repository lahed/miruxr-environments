#!/usr/bin/env python3
"""Los entornos 360 de MiruXR, listos para la GPU.

Por cada foto del catálogo (Poly Haven, CC0): la baja en JPG 8192×4096, arma la cadena de mipmaps y codifica cada
nivel en ASTC 4×4 sRGB con `astcenc` (ARM), empaquetado en un KTX (v1) que iOS (MTKTextureLoader) y Android
(glCompressedTexImage2D) suben TAL CUAL a la GPU: la misma nitidez 8K con 1 byte por píxel en vez de 4, y sin
decodificar en el teléfono (antes: 134 MB de golpe al decodificar + 172 MB de textura; ahora ~43 MB).

Se publica `<id>.ktx.z` (DEFLATE crudo, RFC 1951: iOS `NSData.decompressed(using: .zlib)`, Android `Inflater(true)`)
para bajar menos (15-34 MB en vez de 43) y el JPG original como respaldo para GPUs sin ASTC.

Uso:  python3 build.py --astcenc /ruta/a/astcenc   → out/<id>.ktx.z, out/<id>.jpg y out/manifest.json
"""
import argparse, hashlib, json, os, struct, subprocess, sys, tempfile, urllib.request, zlib
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

# El mismo catálogo que el núcleo (miruxr-spatial: crates/xrkit/src/environments.rs, DOWNLOADABLE).
IDS = ["fish_hoek_beach", "umhlanga_sunrise", "kiara_1_dawn", "qwantani_dusk_2",
       "misty_pines", "rogland_clear_night", "pretville_cinema", "fireplace"]
SRC = "https://dl.polyhaven.org/file/ph-assets/HDRIs/extra/Tonemapped%20JPG/{id}.jpg"

GL_COMPRESSED_SRGB8_ALPHA8_ASTC_4x4_KHR = 0x93D0
GL_RGBA = 0x1908
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--astcenc", required=True)
    ap.add_argument("--quality", default="-medium")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    manifest = []
    for id_ in (a.only or IDS):
        manifest.append(build(a.astcenc, id_, out, out, a.quality))
        print(f"  ✓ {id_}.ktx {manifest[-1]['ktx_bytes'] / 1048576:.1f} MB ({manifest[-1]['levels']} niveles)", flush=True)
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=2)


if __name__ == "__main__":
    sys.exit(main())
