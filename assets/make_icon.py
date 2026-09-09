# =============================================================================
# make_icon.py — Gera assets/app.ico (ICO multi-size) para o build
# =============================================================================
#
# app.ico está no .gitignore (é artefato gerado), então precisa ser recriado
# num clone limpo antes de rodar o PyInstaller:
#
#     .venv\Scripts\python.exe assets\make_icon.py
#
# Desenha a mesma bateria que o ui_main._create_icon() usa na bandeja, em
# amarelo (estado "aguardando"), nos tamanhos que o Windows pede: 16, 32, 48,
# 64 e 256 px.
# =============================================================================

import os
from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")

CORPO  = (38, 44, 52, 255)      # carcaça escura da bateria
CARGA  = (217, 147, 10, 255)    # amarelo — mesmo tom do ícone "aguardando"
BORDA  = (232, 237, 238, 255)


def desenhar(size):
    """Bateria vertical vista de frente, centralizada no canvas."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    u = size / 32.0                       # unidade proporcional ao tamanho
    largura = 14 * u
    altura = 22 * u
    x0 = (size - largura) / 2
    y0 = (size - altura) / 2 + 1.5 * u

    # Terminal (o "pino" no topo)
    tw = 6 * u
    d.rectangle(
        [x0 + (largura - tw) / 2, y0 - 2.5 * u, x0 + (largura + tw) / 2, y0],
        fill=BORDA,
    )

    # Corpo
    raio = max(1, int(2 * u))
    d.rounded_rectangle([x0, y0, x0 + largura, y0 + altura], radius=raio,
                        fill=CORPO, outline=BORDA, width=max(1, int(u)))

    # Nível de carga — preenche ~70% de baixo para cima
    m = 2.5 * u
    topo_carga = y0 + altura - (altura - 2 * m) * 0.70 - m
    d.rounded_rectangle(
        [x0 + m, topo_carga, x0 + largura - m, y0 + altura - m],
        radius=max(1, int(u)), fill=CARGA,
    )

    return img


def main():
    tamanhos = [16, 32, 48, 64, 256]
    imagens = [desenhar(s) for s in tamanhos]

    # save() com append_images grava um ICO multi-resolução de verdade.
    imagens[-1].save(OUT, format="ICO",
                     sizes=[(s, s) for s in tamanhos],
                     append_images=imagens[:-1])

    print(f"OK -> {OUT}  ({os.path.getsize(OUT)} bytes, {len(tamanhos)} resolucoes)")


if __name__ == "__main__":
    main()
