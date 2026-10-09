#!/usr/bin/env python3
"""Editable, positioned LaTeX reconstruction with a separate text-free artwork layer."""
from pathlib import Path
from collections import defaultdict
import argparse, io, json, math, re, shutil, subprocess, tempfile, unicodedata


def escaped(s):
    special={'\\':r'\textbackslash{}','{':r'\{','}':r'\}','%':r'\%','#':r'\#',
             '&':r'\&','_':r'\_','$':r'\$','^':r'\textasciicircum{}','~':r'\textasciitilde{}'}
    return ''.join(special.get(c,c) for c in s if not unicodedata.category(c).startswith('C'))


def norm(s):
    return re.sub(r'^[A-Z]{6}\+','',s).replace(' ','')


def font_data(data,ext):
    from fontTools.ttLib import TTFont
    from fontTools import t1Lib,cffLib,agl
    if ext in ('ttf','otf'):
        ft=TTFont(io.BytesIO(data));order=ft.getGlyphOrder();gs=ft.getGlyphSet()
        cmap=(ft.getBestCmap() or {}) if 'cmap' in ft else {};upem=ft['head'].unitsPerEm
        known={g:cp for cp,g in cmap.items()}
    elif ext=='cff':
        cff=cffLib.CFFFontSet();cff.decompile(io.BytesIO(data),None);top=cff.topDictIndex[0]
        order=list(top.charset);gs=top.CharStrings;upem=round(1/top.FontMatrix[0]);known={}
        for g in order:
            try:
                u=agl.toUnicode(g)
                if len(u)==1:known[g]=ord(u)
            except Exception:pass
        ft=None
    elif ext in ('pfa','pfb'):
        # Embedded Type1 streams may omit the external-file eexec trailer.
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'font.pfa';p.write_bytes(data if b'cleartomark' in data[-600:] else data+b'\n'+b'0'*512+b'\ncleartomark\n')
            ft=t1Lib.T1Font(str(p));gs=ft.getGlyphSet()
        order=list(gs);upem=round(1/ft['FontMatrix'][0]);known={}
        for g in order:
            try:
                u=agl.toUnicode(g)
                if len(u)==1:known[g]=ord(u)
            except Exception:pass
        ft=None
    else:raise ValueError(f'unsupported embedded font: {ext}')
    return {'order':order,'gs':gs,'upem':upem,'known':known,'ft':ft,'mapping':{},'ext':ext}


def save_font(font,path,name):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.pens.cu2quPen import Cu2QuPen
    order=font['order'];mapping={cp:order[gid] for cp,gid in font['mapping'].items() if 0<=gid<len(order) and cp>0}
    # Also expose ordinary characters present in the original font for future edits.
    for g,cp in font['known'].items():mapping.setdefault(cp,g)
    gs=font['gs'];glyf={};metrics={}
    for g in order:
        pen=TTGlyphPen(None);quad=Cu2QuPen(pen,max_err=font['upem']/2000,reverse_direction=True)
        from fontTools.pens.recordingPen import DecomposingRecordingPen
        recording=DecomposingRecordingPen(gs);gs[g].draw(recording);recording.replay(quad)
        glyph=pen.glyph();glyf[g]=glyph
        if glyph.numberOfContours:glyph.recalcBounds(None)
        metrics[g]=(round(gs[g].width),getattr(glyph,'xMin',0))
    if 32 not in mapping:
        g='pdfspace';order=order+[g];glyf[g]=TTGlyphPen(None).glyph();metrics[g]=(round(font['upem']*.25),0);mapping[32]=g
    fb=FontBuilder(font['upem'],isTTF=True);fb.setupGlyphOrder(order);fb.setupCharacterMap(mapping)
    fb.setupGlyf(glyf);fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=font['upem'],descent=-round(font['upem']*.3))
    fb.setupNameTable({'familyName':name,'styleName':'Regular','uniqueFontIdentifier':name,'fullName':name,'psName':name})
    fb.setupOS2(sTypoAscender=font['upem'],sTypoDescender=-round(font['upem']*.3),usWinAscent=round(font['upem']*1.4),usWinDescent=round(font['upem']*.4))
    fb.setupPost();fb.setupMaxp();fb.save(path)


def color_rgb(span,fitz):
    c=span['color']
    if len(c)==1:return [c[0]]*3
    if len(c)==3:return list(c)
    if len(c)==4:
        c,m,y,k=c;return [1-min(1,c+k),1-min(1,m+k),1-min(1,y+k)]
    return [0,0,0]


def get_runs(trace):
    """Split a paint operation into actual lines, retaining literal text and inferred spaces."""
    dx,dy=trace['dir'];lines=[];current=[];prev=None
    chars=[]
    ligatures={'ff':0xfb00,'fi':0xfb01,'fl':0xfb02,'ffi':0xfb03,'ffl':0xfb04,'st':0xfb06}
    for ch in trace['chars']:
        if ch[1] < 0 and chars and ch[2] == chars[-1][2]:
            prevchar=chars[-1]
            combined=unicodedata.normalize('NFKC',chr(prevchar[0]))+chr(ch[0])
            if combined in ligatures:
                chars[-1]=(ligatures[combined],prevchar[1],prevchar[2],prevchar[3]);continue
        chars.append(ch)
    for char in chars:
        cp,gid,origin,box=char
        if cp<0 or cp>0x10ffff:cp=0xfffd
        char=(cp,gid,origin,box)
        if prev:
            vx,vy=origin[0]-prev[2][0],origin[1]-prev[2][1]
            gap=(origin[0]-prev[3][2]) if abs(dy)<.01 and dx>0 else 0
            if abs(-dy*vx+dx*vy)>.3 or dx*vx+dy*vy < -.5 or gap>max(6,trace['size']*.85):
                if current:lines.append(current)
                current=[]
        current.append(char);prev=char
    if current:lines.append(current)
    for line in lines:
        text='';prev=None
        for ch in line:
            cp,gid,org,box=ch
            if prev and cp!=32 and prev[0]!=32:
                if abs(dy)<.01:
                    gap=(org[0]-prev[3][2]) if dx>0 else (prev[3][0]-org[0])
                else:
                    gap=0
                if gap>max(.5,trace['size']*.12):text+=' '
            text+=chr(cp);prev=ch
        first,last=line[0],line[-1]
        if abs(dy)<.01:
            width=last[3][2]-first[2][0] if dx>0 else first[2][0]-last[3][0]
        else:
            width=abs((last[2][0]-first[2][0])*dx+(last[2][1]-first[2][1])*dy)+trace['size']*.5
        if text.strip():yield {'text':text,'origin':list(first[2]),'width':max(.1,width),'chars':line}


def convert(source,output,compile_pdf=False):
    import pymupdf as fitz
    source=Path(source).expanduser().resolve(strict=True);output=Path(output).expanduser().resolve()
    if output.exists():raise ValueError(f'输出目录已存在：{output}')
    engine=shutil.which('xelatex')
    if compile_pdf and not engine:raise ValueError('缺少 XeLaTeX，请安装 TeX Live / MacTeX / MiKTeX。')
    output.parent.mkdir(parents=True,exist_ok=True)
    report={'mode':'positioned-editable','warnings':[],'pages':[],'fonts':{}}
    with fitz.open(source) as doc,tempfile.TemporaryDirectory(dir=output.parent,prefix='pdf-latex-') as temp:
        if not doc.is_pdf or doc.needs_pass:raise ValueError('需要未加密 PDF。')
        root=Path(temp)/'project';root.mkdir()
        for folder in ['pages','assets','fonts']:(root/folder).mkdir()
        fonts={};page_fonts={};traces_by_page=[]
        for p in doc:
            if p.rotation:p.remove_rotation()
            traces_by_page.append(p.get_texttrace())
            candidates=defaultdict(list)
            for info in p.get_fonts(full=True):
                xref,ext,_,base,*_=info
                if xref not in fonts:
                    try:
                        _,ext,_,data=doc.extract_font(xref)
                        if not data:raise ValueError('no font program')
                        fonts[xref]=font_data(data,ext);fonts[xref]['base']=base
                    except Exception as exc:
                        fonts[xref]={'error':str(exc),'base':base}
                candidates[norm(base)].append(xref)
            page_fonts[p.number]=candidates
        all_runs=[]
        for pi,traces in enumerate(traces_by_page):
            runs=[];fallbacks=set()
            for tr in traces:
                if tr['type']==3 or tr['opacity']<=0:continue
                candidates=page_fonts[pi].get(norm(tr['font']),[])
                def score(x):
                    font=fonts[x]
                    if 'error' in font:return -1e9
                    total=0
                    for cp,gid,*_ in tr['chars']:
                        if gid<0 or gid>=len(font['order']):total-=50;continue
                        known=font['known'].get(font['order'][gid])
                        total+=2 if known==cp else (-3 if known is not None else 0)
                    return total
                valid=[x for x in candidates if 'error' not in fonts[x]]
                chosen=max(valid,key=score) if valid else None
                if chosen is None:fallbacks.add(tr['font'])
                for run in get_runs(tr):
                    if chosen is not None:
                        for cp,gid,*_ in run['chars']:
                            if gid >= 0:fonts[chosen]['mapping'][cp]=gid
                    run.update({'font':chosen,'font_name':tr['font'],'size':tr['size'],
                                'color':color_rgb(tr,fitz),'opacity':tr['opacity'],
                                'angle':-math.degrees(math.atan2(tr['dir'][1],tr['dir'][0]))})
                    del run['chars'];runs.append(run)
            if not runs:report['warnings'].append(f'第 {pi+1} 页无文字层，仅保留背景；如需编辑图内文字，请先 OCR。')
            report['pages'].append({'page':pi+1,'text_runs':len(runs),'fallback_fonts':sorted(fallbacks)})
            all_runs.append(runs)
        if not any(all_runs):raise ValueError('整份 PDF 没有可提取文字层，请先 OCR。')
        # Reconstruct embedded font outlines and expose their Unicode mapping to XeLaTeX.
        font_commands=[]
        for xref,font in fonts.items():
            if 'error' in font or not font.get('mapping'):continue
            name=f'pdf-font-{xref}';save_font(font,root/'fonts'/f'{name}.ttf',name)
            font_commands.append(rf'\expandafter\newfontfamily\csname pdfFont{xref}\endcsname[Path=fonts/,Ligatures=NoCommon,RawFeature=-kern]{{{name}.ttf}}')
            report['fonts'][str(xref)]={'original':font['base'],'file':f'fonts/{name}.ttf','unicode_characters':len(font['mapping'])}
        (root/'fonts.tex').write_text('\n'.join(font_commands)+'\n',encoding='utf-8')
        # Remove actual text objects without painting white boxes, touching pixels or vector shapes.
        artwork=fitz.open();artwork.insert_pdf(doc)
        for p in artwork:
            p.add_redact_annot(p.rect,fill=False,cross_out=False)
            p.apply_redactions(images=0,graphics=0,text=0)
        residual=sum(len(p.get_text().strip()) for p in artwork)
        if residual:raise ValueError(f'背景分离不完整：仍有 {residual} 个文字字符。')
        artwork.save(root/'assets'/'artwork.pdf',garbage=4,deflate=True)
        artwork.close()
        report['artwork_text_characters']=residual
        # Standalone raster assets are useful for editing/replacing photographs.
        (root/'assets'/'images').mkdir()
        image_manifest=[];seen=set()
        for page in doc:
            for info in page.get_images(full=True):
                xref,smask=info[:2]
                if xref in seen:continue
                seen.add(xref)
                try:
                    extracted=doc.extract_image(xref)
                    if not smask and extracted['ext'] in ('jpeg','png'):
                        image_name=f"image-{xref}.{extracted['ext']}"
                        (root/'assets'/'images'/image_name).write_bytes(extracted['image'])
                    else:
                        pix=fitz.Pixmap(doc,xref)
                        if smask and not pix.alpha:pix=fitz.Pixmap(pix,fitz.Pixmap(doc,smask))
                        if pix.n-pix.alpha>3:pix=fitz.Pixmap(fitz.csRGB,pix)
                        image_name=f'image-{xref}.png';pix.save(root/'assets'/'images'/image_name)
                    image_manifest.append({'file':'images/'+image_name,'first_page':page.number+1,'xref':xref,
                                           'rectangles':[list(r) for r in page.get_image_rects(xref)]})
                except Exception as exc:report['warnings'].append(f'独立图片 {xref} 导出失败（背景层仍保留）：{exc}')
        (root/'assets'/'images.json').write_text(json.dumps(image_manifest,indent=2),encoding='utf-8')
        page_inputs=[]
        for pi,(page,runs) in enumerate(zip(doc,all_runs),1):
            width,height=page.rect.width,page.rect.height
            lines=[f'% Page {pi}. Edit text inside the final argument of each PDFText command.',
                   f'% Background is separately stored in assets/artwork.pdf, page {pi}.']
            for run in runs:
                x,y=run['origin'];r,g,b=run['color'];fid=run['font'] if run['font'] is not None else 'Fallback'
                # Keep one literal string per line/style run, not a screenshot or per-glyph outline.
                lines.append(rf'\PDFText{{{x:.4f}}}{{{height-y:.4f}}}{{{run["angle"]:.4f}}}{{{fid}}}{{{run["size"]:.4f}}}{{{run["width"]:.4f}}}{{{r:.5f},{g:.5f},{b:.5f}}}{{{escaped(run["text"])}}}')
            (root/'pages'/f'page-{pi:03d}.tex').write_text('\n'.join(lines)+'\n',encoding='utf-8')
            page_inputs.append(rf'\PDFPage{{{width:.4f}}}{{{height:.4f}}}{{{pi}}}{{pages/page-{pi:03d}.tex}}')
        preamble=r'''% Compile with XeLaTeX. All text in pages/*.tex is editable.
\documentclass{article}
\usepackage{fontspec,graphicx,xcolor,eso-pic}
\usepackage[margin=0pt]{geometry}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\newfontfamily\pdfFontFallback{texgyreheros-regular.otf}
\input{fonts.tex}
\newcommand{\PDFText}[8]{%
  \put(#1,#2){\rotatebox[origin=lB]{#3}{%
    \begingroup\csname pdfFont#4\endcsname\fontsize{#5bp}{#5bp}\selectfont
    \color[rgb]{#7}\resizebox{#6bp}{\height}{#8}\endgroup}}%
}
\newcommand{\PDFPage}[4]{%
  \clearpage
  \pdfpagewidth=#1bp\pdfpageheight=#2bp
  \paperwidth=#1bp\paperheight=#2bp
  \AddToShipoutPictureBG*{\setlength{\unitlength}{1bp}%
    \put(0,0){\includegraphics[page=#3,width=#1bp,height=#2bp]{assets/artwork.pdf}}%
    \input{#4}}%
  \null\newpage
}
\begin{document}
'''
        # XeTeX uses special page-size commands; geometry's paper sizes follow each page.
        preamble=preamble.replace(r'\pdfpagewidth=#1bp\pdfpageheight=#2bp',r'\special{papersize=#1bp,#2bp}')
        (root/'main.tex').write_text(preamble+'\n'.join(page_inputs)+'\n\\end{document}\n',encoding='utf-8')
        (root/'README.md').write_text(PROJECT_README,encoding='utf-8')
        (root/'layout.json').write_text(json.dumps(all_runs,ensure_ascii=False,indent=2),encoding='utf-8')
        if compile_pdf:
            result=subprocess.run([engine,'-no-shell-escape','-halt-on-error','-interaction=nonstopmode','main.tex'],cwd=root,capture_output=True,text=True,errors='replace',timeout=300)
            log=result.stdout+result.stderr;(root/'compile.log').write_text(log,encoding='utf-8')
            report['compiled']=result.returncode==0
            report['missing_glyphs']=sorted(set(re.findall(r'Missing character:.*',log)))
            if result.returncode:
                report['warnings'].append('编译失败，请查看 compile.log。');(root/'main.pdf').unlink(missing_ok=True)
            for suffix in ['aux','log']:(root/f'main.{suffix}').unlink(missing_ok=True)
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if output.exists():raise ValueError('输出目录在运行期间被创建。')
        root.rename(output)
    return report


PROJECT_README = r"""# 编辑这个 LaTeX 工程

使用 XeLaTeX 编译 main.tex。原 PDF 不参与编译。

- pages/page-001.tex 等文件：可编辑文字，每个 PDFText 命令的最后一对花括号是正文。
- assets/artwork.pdf：已经移除文字对象的背景及图形层，保留照片、透明色块、图表线条等。
- assets/images/：单独导出的位图素材。它们用于另行编辑/复用；编译引用的是 artwork.pdf，替换这里的 PNG 不会自动修改背景层。
- fonts/ 和 fonts.tex：恢复的嵌入字体及 LaTeX 字体配置，必须随工程保留。
- report.json：分离、字体回退、编译和缺字信息。layout.json 为提取的文字和坐标参考，修改它不会自动更新 tex。

例如搜索原句，在 pages/*.tex 的最后一个参数中修改文字，然后重新运行：

```bash
xelatex -no-shell-escape -halt-on-error main.tex
```

PDFText 参数依次为：x、y（从页左下角起，单位 bp）、旋转角度、字体编号、字号、目标行宽、RGB 颜色、文字。
文字按固定行框排列。默认会水平缩放至目标行宽；长篇改写需手动调整行宽、字号及后续行坐标，不会自动重新分页。
LaTeX 特殊字符需要转义，例如 & 写为 \&，% 写为 \%。

数学内容按原符号及位置保留，并非自动恢复成 equation/align 结构。图表数值文字可编辑，但柱线形状和图内的栅格化文字仍属于图形。
部分原 PDF 字体是子集，新增原稿没有的字可能缺字；可在 fonts.tex 中将对应字体换成已安装的完整字体。编译日志出现 Missing character 时必须校对。
标志中已转为矢量轮廓的字和照片中的文字不是 PDF 文字对象，仍留在背景中。
"""

def main():
    p=argparse.ArgumentParser(description='把 PDF 分为不含正文的背景/插图层和按原位置排版的可编辑 LaTeX 文字。')
    p.add_argument('pdf',type=Path);p.add_argument('-o','--output',type=Path,required=True)
    p.add_argument('--compile',action='store_true',help='同时使用 XeLaTeX 编译')
    a=p.parse_args()
    try:r=convert(a.pdf,a.output,a.compile)
    except Exception as e:p.exit(1,f'转换失败：{e}\n')
    print(f'已生成：{a.output.resolve() / "main.tex"}')
    for w in r['warnings']:print(w)
    if a.compile and (not r.get('compiled') or r.get('missing_glyphs')):return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
