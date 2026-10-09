# PDF → Separated Text and Graphics, Preserving the Original Layout, as Editable LaTeX (Third Edition)

Use cases: brochures with an independent text layer, pages with text overlaid on background photos, and two-column papers with mixed text and graphics.

example: left side -> generated tex; right side -> original pdf
<img width="2782" height="1566" alt="169ba1a140f4580813f097ecd875a872" src="https://github.com/user-attachments/assets/8df80622-890c-4a0f-96ac-0ece696190a2" />


## Installation and Usage

Requires Python 3.10+:

```bash
python3 -m pip install -r requirements.txt
python3 pdf_to_latex.py "input.pdf" -o "new_output_directory" --compile
```

`--compile` requires XeLaTeX (TeX Live / MacTeX / MiKTeX). Without it, only the project is generated. The output directory must not already exist. You can also upload the project to Overleaf and choose XeLaTeX to compile.

The earlier `--mode notebook`, `--columns`, and `--ocr-language` options do not apply to the third edition. This version directly reads the real coordinates and text layer from the original PDF, no longer guesses the column layout and re-typesets, and does not include OCR.

## Actual Implementation

1. Extract text content, original positions, font sizes, colors, rotation, and embedded fonts.
2. Remove text objects from the page to generate a separate `assets/artwork.pdf`; photos, vector graphics, chart lines, and transparent backgrounds remain.
3. Restore fonts to Unicode fonts usable by LaTeX. Output editable `pages/page-XXX.tex` at the original positions.
4. Also export standalone bitmap assets in `assets/images/`, recording the source page and coordinates.
5. Compile `main.tex` to recombine the graphics layer and editable text. The original input PDF is not needed.

This is not a wrapper that references pages of the original PDF: the text objects have already been removed from the background file, and the text comes from the `.tex`. Text changes will be reflected in the compiled result.

## How to Edit

Open `pages/page-001.tex` and search for the sentence you want to modify. The text is in the last pair of braces of each `\PDFText` command. Edit it directly and recompile `main.tex`.

For example:

```latex
\PDFText{54}{390}{0}{193}{36}{330}{1,1,1}{PORTS THRIVE WITH}
```

The parameters are, in order: position x, position y (origin at the bottom-left, unit bp), rotation angle, font number, font size, target line width, RGB color, text.

When editing, LaTeX special characters still need to be escaped, for example `&` becomes `\&`.

## Scope and Limitations

- **Editing at original positions, not automatic reflow.** Line boxes, pagination, and image positions are fixed. Text is horizontally scaled to the original line width by default; extensive rewriting requires adjusting line width, font size, and the positions of other lines, and cannot automatically push later paragraphs aside.
- **Formulas retain symbols and positions, but semantic source is not recovered.** Fractions, superscripts, and subscripts may consist of multiple text fragments and the original graphic lines, and will not be automatically converted into `equation` / `align`.
- **Graphics and images are retained as graphic resources.** PDF text objects inside figures are also separated out, but text already burned into images, and text converted to outlines in logos, will not become editable body text.
- Bitmaps are exported separately for reuse; compilation references `artwork.pdf`, and replacing files in `images/` will not automatically update the graphics layer. To modify the overall graphics layer, you can replace `artwork.pdf` with one of the same page size, or place another image in `main.tex`.
- A few fonts that cannot be restored use fallback fonts; see `report.json` for the detailed list. Embedded fonts may contain only the characters used in the original document; when newly added characters are missing, you need to replace the corresponding font in `fonts.tex` with a complete font.
- Complex text clipping, text occlusion, abnormal text transformations, stroked text, transparent text, and non-horizontal writing are not yet guaranteed to be reproduced exactly. New documents still need to be checked.
- Scanned PDFs with no text layer at all will clearly report an error; pages with no text will retain the background and be noted in the report, and such pages cannot be called editable body text.

- 
# PDF → 图文分离、保留原布局的可编辑 LaTeX（第三版）

适用场景：有独立文字层的宣传册、背景照片上叠加文字的页面，以及双栏论文和图文混排。

## 安装与使用

需要 Python 3.10+：

```bash
python3 -m pip install -r requirements.txt
python3 pdf_to_latex.py "输入.pdf" -o "新的输出目录" --compile
```

`--compile` 需要 XeLaTeX（TeX Live / MacTeX / MiKTeX）。不加它只生成工程。输出目录必须不存在。也可以把工程上传到 Overleaf，选择 XeLaTeX 编译。

此前的 `--mode notebook`、`--columns`、`--ocr-language` 不适用于第三版。本版直接读取原 PDF 中的真实坐标和文字层，不再猜测分栏后重新排版，不包含 OCR。

## 实际实现

1. 提取文字内容、原始位置、字号、颜色、旋转方向和嵌入字体。
2. 从页面中移除文字对象，生成独立的 `assets/artwork.pdf`；照片、矢量图、图表线条和透明背景仍保留。
3. 恢复字体为 LaTeX 可用的 Unicode 字体。按原位置输出可编辑的 `pages/page-XXX.tex`。
4. 另外导出 `assets/images/` 中的独立位图素材，并记录来源页和坐标。
5. 编译 `main.tex` 将图形层和可编辑文字重新组合。不需要原输入 PDF。

这不是引用原 PDF 页面的包装器：背景文件中已删除文字对象，文字来自 `.tex`。文字改动会反映在编译结果中。

## 如何编辑

打开 `pages/page-001.tex`，搜索想修改的原句。每个 `\PDFText` 命令最后一对花括号内为文字，直接修改后重新编译 `main.tex`。

例如：

```latex
\PDFText{54}{390}{0}{193}{36}{330}{1,1,1}{PORTS THRIVE WITH}
```

参数依次是位置 x、位置 y（左下角为原点、单位 bp）、旋转角、字体编号、字号、目标行宽、RGB 颜色、文字。

编辑时，LaTeX 特殊字符仍须转义，例如 `&` 写成 `\&`。

## 范围与限制

- **按原位置编辑，非自动重排。** 行框、分页和图片位置固定。文字默认水平缩放至原行宽；大段改写需调整行宽、字号及其他行的位置，不能自动推开后面的段落。
- **公式保留符号和位置，不恢复语义源码。** 分式、上下标可以由多个文字片段和原图形线条组成，不会自动转换成 `equation` / `align`。
- **图形与图片保留为图形资源。** 图中的 PDF 文字对象也会分离，但已经烧录进图片的字，以及标志中转为轮廓的字，不会变成可编辑正文。
- 位图单独导出便于复用；编译引用 `artwork.pdf`，替换 `images/` 内文件不会自动更新图形层。要修改整体图形层，可替换同页尺寸的 `artwork.pdf`，或在 `main.tex` 中另放图片。
- 少数无法恢复的字体使用回退字体，详细名单见 `report.json`。嵌入字体可能只有原稿用过的字符；新增字符缺字时，需要把 `fonts.tex` 中的对应字体换成完整字体。
- 复杂文字裁剪、文字遮挡、非正常文字变换、描边文字、透明文字及非水平书写尚不保证原样还原。新文档仍需检查。
- 完全没有文字层的扫描 PDF 会明确报错；部分无文字页面会保留背景并在报告中提示，不能把这些页面称为可编辑正文。

