# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys
import inspect
import pathlib
import datetime
sys.path.insert(0, os.path.abspath('.'))

# HACKS - credit to "https://github.com/rodluger/starry_process"
sys.path.insert(1, os.path.dirname(os.path.abspath(__file__)))
import hacks

from configparser import ConfigParser
conf = ConfigParser()

docs_root = pathlib.Path(__file__).parent.resolve()
conf.read([str(docs_root / '..' / 'setup.cfg')])
setup_cfg = dict(conf.items('metadata'))

# -- Project information -----------------------------------------------------

project = setup_cfg['name']
author = setup_cfg['author']
copyright = '{0}, {1}'.format(
    datetime.datetime.now().year, setup_cfg['author'])


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.mathjax",
    "matplotlib.sphinxext.plot_directive",
    "nbsphinx",
    'sphinx_automodapi.automodapi',
    'sphinx_automodapi.smart_resolver',
    'sphinx.ext.graphviz',
    'IPython.sphinxext.ipython_console_highlighting',
    'IPython.sphinxext.ipython_directive',
    'numpydoc',
    'sphinxcontrib.bibtex',
    'sphinx.ext.intersphinx',
    'sphinx_copybutton',
    'sphinx.ext.linkcode',
    'sphinx_tabs.tabs'
]

sphinx_tabs_disable_tab_closing = True

intersphinx_mapping = {'python': ('https://docs.python.org/3', None),
                       'matplotlib': ('https://matplotlib.org/stable', None),
                       'seaborn': ('https://seaborn.pydata.org', None),
                       'scipy': ('https://docs.scipy.org/doc/scipy', None),
                       'astropy': ('https://docs.astropy.org/en/stable', None)}

bibtex_bibfiles = ['notebooks/refs.bib']

# fix numpydoc autosummary
numpydoc_show_class_members = False

# use blockquotes (numpydoc>=0.8 only)
numpydoc_use_blockquotes = True

# auto-insert plot directive in examples
numpydoc_use_plots = True


# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = 'pydata_sphinx_theme'

html_theme_options = {
    "logo": {
        "link": "index",
        "image_light": "logo.png",
        "image_dark": "logo_darkmode.png",
    },
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/TomWagg/cosmic-gala",
            "icon": "fab fa-github-square",
        },
    ],
    "footer_items": ["copyright", "last-updated"],
}

html_last_updated_fmt = "%Y %b %d at %H:%M:%S UTC"
html_show_sourcelink = False
html_favicon = "_static/favicon.ico"

html_sidebars = {
    "index": [],
    "**": ["search-field.html", "sidebar-nav-bs.html"]
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']
html_css_files = ["custom.css"]
html_js_files = ['custom.js']

# autodocs
autoclass_content = "both"
autosummary_generate = True
autodoc_docstring_signature = True

# todos
todo_include_todos = True

# nbsphinx
nbsphinx_prolog = """
{% set docname = env.doc2path(env.docname, base=None) %}
.. note:: This tutorial was generated from a Jupyter notebook that can be
          `downloaded here <https://github.com/TeamLEGWORK/LEGWORK/tree/main/docs/{{ docname }}>`_.
          If you'd like to reproduce the results in the notebook, or make changes to the code, we recommend
          downloading this notebook and running it with Jupyter as certain cells (mostly those that change
          plot styles) are excluded from the tutorials.
"""
nbsphinx_prompt_width = "0"

nbsphinx_execute_arguments = [
    "--InlineBackend.figure_formats={'svg', 'pdf'}",
    "--InlineBackend.rc={'figure.dpi': 96}",
]

mathjax3_config = {
    'tex': {'tags': 'ams', 'useLabelIds': True},
}

def linkcode_resolve(domain, info):
    """function for linkcode sphinx extension"""
    def find_func():
        # find the installed module in sys module
        sys_mod = sys.modules[info["module"]]

        # use inspect to find the source code and starting line number
        names = info["fullname"].split(".")
        func = sys_mod
        for name in names:
            func = getattr(func, name)
        source_code, line_num = inspect.getsourcelines(func)

        # get the file name from the module
        file = info["module"].split(".")[-1]

        return file, line_num, line_num + len(source_code) - 1

    # ensure it has the proper domain and has a module
    if domain != 'py' or not info['module']:
        return None

    # attempt to cleverly locate the function in the file
    try:
        file, start, end = find_func()
        # stitch together a github link with specific lines
        filename = "legwork/{}.py#L{}-L{}".format(file, start, end)

    # if you can't find it in the file then just link to the correct file
    except Exception:
        filename = info['module'].replace('.', '/') + '.py'
    return "https://github.com/TeamLEGWORK/LEGWORK/blob/main/{}".format(filename)