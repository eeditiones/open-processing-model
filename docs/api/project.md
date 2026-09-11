# Project

`opm.Project` provides a high-level API into opm. It loads an
`opm.toml` and does what the commands do, taking the same settings from the
config: `transform`, `chunk`, `index` and `coverage`. ODDs compile on
demand into the user cache, as they do for the CLI.

```python
from pathlib import Path

from opm import Project, collect_xpath_errors
from opm.indexing import write_jsonl
from opm.typst_compile import compile_pdf

project = Project.load('edition/opm.toml')

# One document in several formats. The ODD for each mode comes from
# [transform.<mode>] odd, then [transform] odd, then the packaged ODD.
html = project.transform('edition/data/letter.xml')
docx = project.transform('edition/data/letter.xml', mode='docx')       # bytes
toc = project.transform('edition/data/letter.xml', parameters={'mode': 'toc'})

# Typst output compiled to PDF: running typst is up to you.
typst = project.transform('edition/data/letter.xml', mode='typst')
pdf = compile_pdf(typst, root=Path('edition/data'))                    # needs typst

# Chunk a directory into JSON for a static site generator.
run = project.chunk('edition/data/letters', format='json', overwrite=True)
print(run.output_dir, [doc.name for doc in run.documents])

# Search-index records, and the ODD's coverage of the corpus.
write_jsonl(project.index('edition/data'), Path('index.jsonl'))
report = project.coverage('edition/data')

# See the XPath expressions that failed at run time.
with collect_xpath_errors() as log:
    project.transform('edition/data/letter.xml')
for failure in log.ordered_failures():
    print(f'{failure.count}× {failure.expression}: {failure.message}')
```

## In a web service

A `Project` keeps the modules it has loaded and the register documents it has
parsed, so load it once and reuse it. One instance can be shared between
threads. It is a snapshot: after changing an ODD or a register, load a new one.

```python
from lxml import etree
from opm import Project

project = Project.load('/srv/edition/opm.toml')

def render(path: str, view: str = 'div') -> str:
    return project.transform(f'/srv/edition/data/{path}', parameters={'view': view})

def render_fragment(root: etree._Element, xml_id: str) -> str:
    # An element parsed from a file still resolves doc() against that file.
    return project.transform(root, xpath=f'id("{xml_id}")')
```

## Paths

Paths in `opm.toml` are relative to the file's directory. Relative paths
passed to the methods are relative to the current directory, as usual in
Python. The chunk `output_dir` is relative to `Project.root`, which is the
config file's directory unless `Project.load(..., root=...)` says otherwise.

## Settings in code

A project doesn't need a config file:

```python
from pathlib import Path

from opm import Project, ProjectConfig

project = Project(ProjectConfig(parameters={'lang': 'en'}), root='build')
print_project = project.with_config(document_css=Path('print.css'))
```

The functions in [`opm.transform`](transform.md), [`opm.chunking`](chunking.md)
and [`opm.indexing`](indexing.md) are the layer below `Project`, for callers
that need finer control.

::: opm.project
