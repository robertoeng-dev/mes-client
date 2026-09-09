# =============================================================================
# make_installer_images.py — Gera as imagens do wizard do Inno Setup
# =============================================================================
#
# installer_banner.bmp e installer_header.bmp estao no .gitignore (sao
# artefatos gerados), entao precisam ser recriados num clone limpo antes de
# compilar o instalador:
#
#     .venv\Scripts\python.exe assets\make_installer_images.py
#
# Formato exigido pelo Inno Setup: BMP 24 bits, sem canal alpha.
#   WizardImageFile      -> 164 x 314  (painel lateral da primeira pagina)
#   WizardSmallImageFile ->  55 x  55  (canto superior das paginas internas)
# =============================================================================

import os
from PIL import Image, ImageDraw

AQUI = os.path.dirname(os.path.abspath(__file__))

# Mesma paleta escura do app
FUNDO_TOPO  = (18, 26, 32)
FUNDO_BASE  = (12, 18, 22)
ACENTO      = (16, 100, 111)
ACENTO_CLARO = (87, 184, 196)
CARGA       = (217, 147, 10)
TEXTO       = (232, 237, 238)
TEXTO_FRACO = (122, 140, 146)


def gradiente(largura, altura):
    """Fundo escuro com leve gradiente vertical."""
    img = Image.new("RGB", (largura, altura), FUNDO_TOPO)
    d = ImageDraw.Draw(img)
    for y in range(altura):
        t = y / max(1, altura - 1)
        cor = tuple(
            int(FUNDO_TOPO[i] + (FUNDO_BASE[i] - FUNDO_TOPO[i]) * t)
            for i in range(3)
        )
        d.line([(0, y), (largura, y)], fill=cor)
    return img


def bateria(d, cx, cy, largura, altura):
    """Mesma bateria do icone da bandeja, desenhada no centro indicado."""
    x0, y0 = cx - largura / 2, cy - altura / 2
    terminal = largura * 0.42
    d.rectangle(
        [cx - terminal / 2, y0 - altura * 0.09, cx + terminal / 2, y0],
        fill=TEXTO,
    )
    d.rounded_rectangle(
        [x0, y0, x0 + largura, y0 + altura],
        radius=int(largura * 0.14), fill=(30, 39, 45),
        outline=TEXTO, width=max(1, int(largura * 0.06)),
    )
    m = largura * 0.18
    topo = y0 + altura - (altura - 2 * m) * 0.70 - m
    d.rounded_rectangle(
        [x0 + m, topo, x0 + largura - m, y0 + altura - m],
        radius=int(largura * 0.07), fill=CARGA,
    )


def banner():
    """Painel lateral 164x314 da pagina de boas-vindas."""
    L, A = 164, 314
    img = gradiente(L, A)
    d = ImageDraw.Draw(img)

    bateria(d, L / 2, 96, 52, 84)

    # Filete de acento sob a bateria
    d.rectangle([L / 2 - 26, 158, L / 2 + 26, 160], fill=ACENTO_CLARO)

    d.text((L / 2, 182), "MES CLIENT", fill=TEXTO, anchor="mm")
    d.text((L / 2, 199), "Salcomp Manaus", fill=TEXTO_FRACO, anchor="mm")

    # Faixa de acento na base
    d.rectangle([0, A - 4, L, A], fill=ACENTO)

    return img


def header():
    """Icone 55x55 do canto superior das paginas internas."""
    L = 55
    img = Image.new("RGB", (L, L), FUNDO_TOPO)
    d = ImageDraw.Draw(img)
    bateria(d, L / 2, L / 2 - 1, 22, 34)
    d.rectangle([0, L - 2, L, L], fill=ACENTO)
    return img


def main():
    saidas = [
        ("installer_banner.bmp", banner()),
        ("installer_header.bmp", header()),
    ]
    for nome, img in saidas:
        caminho = os.path.join(AQUI, nome)
        # BMP 24 bits: o Inno Setup rejeita imagem com canal alpha
        img.convert("RGB").save(caminho, format="BMP")
        print(f"OK -> {caminho}  ({img.size[0]}x{img.size[1]}, "
              f"{os.path.getsize(caminho)} bytes)")


if __name__ == "__main__":
    main()
