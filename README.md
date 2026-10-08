# MiruXR · entornos 360

Los fondos 360 de [MiruXR](https://miruxr.com) listos para la GPU de los teléfonos: cada foto en **ASTC 4×4 sRGB
con mipmaps** (KTX v1), que iOS y Android suben tal cual, sin decodificar. La misma nitidez 8K (PSNR ~60 dB frente
al original) con 1 byte por píxel en vez de 4: **~43 MB de textura en vez de ~172 MB**, y sin el pico de memoria de
decodificar una foto 8K en el teléfono.

| Archivo del release | Qué es |
|---|---|
| `<id>.ktx.z` | La textura ASTC (KTX v1) comprimida con DEFLATE crudo (RFC 1951) para la descarga |
| `<id>.jpg` | La foto original (respaldo para GPUs sin ASTC) |
| `manifest.json` | Tamaños, niveles y SHA-256 de cada textura |

## Fotos

Todas de [Poly Haven](https://polyhaven.com), licencia **CC0** (dominio público: uso y redistribución libres). Gracias
a Poly Haven y a sus autores.

`fish_hoek_beach` · `umhlanga_sunrise` · `kiara_1_dawn` · `qwantani_dusk_2` · `misty_pines` · `rogland_clear_night` ·
`pretville_cinema` · `fireplace`

## Regenerar

Requiere Python 3 con Pillow y `astcenc` ([ARM, Apache-2.0](https://github.com/ARM-software/astc-encoder/releases)):

```sh
python3 build.py --astcenc /ruta/a/astcenc          # todas
python3 build.py --astcenc /ruta/a/astcenc --only fireplace
```

La lista de fotos es la del catálogo del núcleo de MiruXR (`environments.rs`); al agregar una, va en los dos lados.
