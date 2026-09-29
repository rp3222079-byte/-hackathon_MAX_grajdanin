# Презентация

- `Domovoy_presentation.pdf` — презентация (16 слайдов, первый — служебный для проверки).
- `presentation.html` — исходник; `{{HASH}}` на первом слайде заменяется commit hash сдаваемой версии.

PDF собирается печатью в Chrome:

```bash
chrome --headless --no-pdf-header-footer --print-to-pdf=Domovoy_presentation.pdf presentation.html
```
