# Vendored MathJax

This directory vendors the browser bundle used as the offline fallback for
HTML SRS collections.

- Package: `mathjax`
- Version: `3.2.2`
- File: `es5/tex-mml-chtml.js`
- Source: `https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js`
- License: Apache-2.0
- SHA-256: `300480069078B5892D2363A2B65E2DFBBF30FE5C80F83EDBFECF4610FD093862`

The generated collection copies this file to
`<collection-root>/assets/mathjax/tex-mml-chtml.js` and loads that local file
directly so formulas work without network access.
