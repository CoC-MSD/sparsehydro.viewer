# sparsehydro-viewer documentation build configuration (adapted from sparsehydro's docs/conf.py).
#
# Build:        sphinx-build -W --keep-going -b html docs docs/_build/html
# Screenshots:  python docs/scripts/screenshots.py   (regenerates docs/_static/screenshots/*.png)

import os
import sys

sys.path.insert(0, os.path.abspath("../src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # autodoc imports modules that import Qt

from sparsehydro_viewer import __version__  # noqa: E402

# -- General configuration -----------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_design",
    "myst_parser",
]

add_module_names = False
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "member-order": "bysource",
}
autodoc_typehints = "description"
autodoc_typehints_format = "short"
autodoc_typehints_description_target = "documented"
autoclass_content = "class"
autosummary_generate = False
napoleon_use_ivar = True

source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
myst_enable_extensions = ["colon_fence", "deflist", "fieldlist", "attrs_inline"]
myst_heading_anchors = 3

master_doc = "index"
project = "SparseHydro Viewer"
author = "Caleb Buahin"
copyright = "2026 Hazen and Sawyer, on behalf of MSDGC"
version = release = __version__
language = "en"

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
}

exclude_patterns = ["_build", "scripts", "Thumbs.db", ".DS_Store", "*.pptx"]
suppress_warnings = ["ref.python", "myst.xref_missing"]
nitpicky = False
pygments_style = "sphinx"

# -- HTML output ---------------------------------------------------------------

html_theme = "pydata_sphinx_theme"
html_title = f"SparseHydro Viewer {release}"
html_theme_options = {
    "icon_links": [
        {"name": "GitHub", "url": "https://github.com/CoC-MSD/sparsehydro.viewer", "icon": "fa-brands fa-github",
         "type": "fontawesome"},
    ],
    "show_toc_level": 2,
    "navbar_end": ["theme-switcher.html", "navbar-icon-links.html"],
    "secondary_sidebar_items": ["page-toc"],
}
html_logo = "../src/sparsehydro_viewer/resources/app-icon.svg"
html_favicon = "../src/sparsehydro_viewer/resources/app-icon.svg"
html_static_path = ["_static"]
htmlhelp_basename = "sparsehydro-viewer-doc"


def setup(app):
    app.add_css_file("viewer.css")
