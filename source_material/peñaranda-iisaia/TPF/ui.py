"""Los detalles del estilo Lamborghini que `config.toml` no puede expresar:
mayusculas obligatorias, tracking uniforme y la tinta negra del boton Giallo.

El resto (paleta, tipografia, radio 0, bordes) vive en `.streamlit/config.toml`.
"""

import streamlit as st

_CSS = """
<style>
/* Tracking 0.0230em uniforme: "wide enough to feel engineered, not cramped" */
.stApp { letter-spacing: 0.023em; }

/* Jerarquia por escala, nunca por peso. Todo titulo va en mayusculas. */
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {
    text-transform: uppercase;
    font-weight: 400;
    line-height: 1.0;
}
.stApp h1 { line-height: 0.92; }

/* Etiquetas y botones tambien en caja alta */
.stApp label, .stApp button { text-transform: uppercase; }

/* Boton Giallo: tinta negra, el blanco no contrasta sobre #ffc000 */
.stApp [data-testid^="stBaseButton-primary"] { color: #000000 !important; }

/* Sin elevacion: la separacion es por contraste de superficie y filete de 1px */
.stApp [data-testid="stVerticalBlockBorderWrapper"],
.stApp button,
.stApp input,
.stApp textarea {
    box-shadow: none !important;
}

/* Los iconos Material se dibujan por ligaduras: el tracking y las mayusculas
   las romperian, asi que se los excluye. */
.stApp [data-testid="stIconMaterial"] {
    letter-spacing: normal !important;
    text-transform: none !important;
}
</style>
"""


def apply_style() -> None:
    st.html(_CSS)
