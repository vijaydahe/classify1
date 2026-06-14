// Package stamp writes a classification label into documents in place, so the
// endpoint agent can enforce the organization's stamping policy automatically as
// it scans — no user action. Word (.docx) gets a banner paragraph at the top of
// the body; plain-text files get a header line. Writes are atomic (temp + rename)
// and idempotent (a file already carrying a CLASSIFICATION marker is skipped).
package stamp

import (
	"archive/zip"
	"bytes"
	"encoding/xml"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/pdfcpu/pdfcpu/pkg/api"
	"github.com/pdfcpu/pdfcpu/pkg/pdfcpu/types"
)

const marker = "CLASSIFICATION"

var textExts = map[string]bool{".txt": true, ".md": true, ".csv": true, ".log": true}

// Supported reports whether this file type can be stamped in place.
func Supported(path string) bool {
	ext := strings.ToLower(filepath.Ext(path))
	return ext == ".docx" || ext == ".pdf" || textExts[ext]
}

// Stamp writes the label into the file per the placement, returning true if it
// modified the file (false if already stamped or unsupported).
func Stamp(path, text, colorHex string) (bool, error) {
	ext := strings.ToLower(filepath.Ext(path))
	switch {
	case ext == ".docx":
		return stampDocx(path, text, colorHex)
	case ext == ".pdf":
		return stampPDF(path, text, colorHex)
	case textExts[ext]:
		return stampText(path, text)
	}
	return false, nil
}

// stampPDF adds a top-centre classification watermark on every page.
func stampPDF(path, text, colorHex string) (bool, error) {
	if has, err := api.HasWatermarksFile(path, nil); err == nil && has {
		return false, nil // already watermarked — keep idempotent
	}
	r, g, b := hexFloats(colorHex)
	desc := fmt.Sprintf("font:Helvetica, points:10, color:%.3f %.3f %.3f, pos:tc, rot:0, op:1, scale:1 abs", r, g, b)
	wm, err := api.TextWatermark(text, desc, true, false, types.POINTS)
	if err != nil {
		return false, err
	}
	tmp := path + ".chtmp"
	if err := api.AddWatermarksFile(path, tmp, nil, wm, nil); err != nil {
		os.Remove(tmp)
		return false, err
	}
	return true, os.Rename(tmp, path)
}

func hexFloats(h string) (float64, float64, float64) {
	h = strings.TrimPrefix(h, "#")
	if len(h) != 6 {
		return 0.86, 0.15, 0.15
	}
	r, _ := strconv.ParseInt(h[0:2], 16, 0)
	g, _ := strconv.ParseInt(h[2:4], 16, 0)
	b, _ := strconv.ParseInt(h[4:6], 16, 0)
	return float64(r) / 255, float64(g) / 255, float64(b) / 255
}

func stampText(path, text string) (bool, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return false, err
	}
	if bytes.Contains(data[:min(len(data), 200)], []byte(marker)) {
		return false, nil
	}
	out := append([]byte(text+"\n"), data...)
	return true, atomicWrite(path, out)
}

// stampDocx injects a bold, coloured paragraph at the start of the document body.
func stampDocx(path, text, colorHex string) (bool, error) {
	zr, err := zip.OpenReader(path)
	if err != nil {
		return false, err
	}
	defer zr.Close()

	color := strings.ToUpper(strings.TrimPrefix(colorHex, "#"))
	var esc bytes.Buffer
	xml.EscapeText(&esc, []byte(text))
	para := `<w:p><w:pPr><w:rPr><w:b/><w:color w:val="` + color + `"/></w:rPr></w:pPr>` +
		`<w:r><w:rPr><w:b/><w:color w:val="` + color + `"/></w:rPr>` +
		`<w:t xml:space="preserve">` + esc.String() + `</w:t></w:r></w:p>`

	buf := new(bytes.Buffer)
	zw := zip.NewWriter(buf)
	modified := false
	for _, f := range zr.File {
		rc, err := f.Open()
		if err != nil {
			return false, err
		}
		content, err := io.ReadAll(rc)
		rc.Close()
		if err != nil {
			return false, err
		}
		if f.Name == "word/document.xml" {
			if bytes.Contains(content, []byte(marker)) {
				return false, nil // already stamped
			}
			idx := bytes.Index(content, []byte("<w:body>"))
			if idx >= 0 {
				insertAt := idx + len("<w:body>")
				content = append(content[:insertAt],
					append([]byte(para), content[insertAt:]...)...)
				modified = true
			}
		}
		w, err := zw.CreateHeader(&zip.FileHeader{Name: f.Name, Method: zip.Deflate})
		if err != nil {
			return false, err
		}
		if _, err := w.Write(content); err != nil {
			return false, err
		}
	}
	if err := zw.Close(); err != nil {
		return false, err
	}
	if !modified {
		return false, nil
	}
	return true, atomicWrite(path, buf.Bytes())
}

// atomicWrite replaces the file via a temp file + rename, preserving the mode.
func atomicWrite(path string, data []byte) error {
	info, _ := os.Stat(path)
	mode := os.FileMode(0o644)
	if info != nil {
		mode = info.Mode()
	}
	tmp := path + ".chtmp"
	if err := os.WriteFile(tmp, data, mode); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
