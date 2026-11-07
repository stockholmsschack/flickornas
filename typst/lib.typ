#let standings_heading(title, group: none) = block(breakable: false, sticky: true)[
  #set text(9pt, font: "Roboto", weight: "regular")
  #grid(
    columns: (1fr, 5cm),
    column-gutter: 0.5cm,
    align: (left + bottom, right + bottom),
    [
      #text(14pt, weight: "bold", fill: rgb("#0072B2"), title)
      #linebreak()
      Utskrift gäller: #datetime.today().display()
      #if group != none [
        #v(0.5em)
        #text(11pt, weight: "bold", fill: rgb("#0072B2"), group)
      ]
    ],
    link("https://www.stockholmsschack.se/juniortavlingar/")[#image("stsf.png", width: 5cm)],
  )
  #v(0.3em)
]

#let stylish_table(
  fill: rgb("efefef"),
  header_color: rgb("c9daf8"),
  striping: "even",
  font: "Roboto",
  size: 7pt,
  stretch: 75%,
  weight: "regular",
  frame_lines: "all",
  frame_stroke: 0.1pt,
  inner_stroke: 0.1pt,
  sides: none,
  ends: true,
  rows: true,
  cols: none,
  header_underline: none,
  stroke_color: rgb("#5c5c4f"),
  raw_size: 8pt,
  col_align: (left),
  body,
) = {
  show raw: set text(size: raw_size)
  let frame() = (
    (x, y) => (
      left: if (x > 0) {
        if cols == true {
          inner_stroke + stroke_color
        } else {
          0pt
        }
      } else {
        if sides == true {
          frame_stroke + stroke_color
        } else {
          0pt
        }
      },
      right: if sides == true {
        frame_stroke + stroke_color
      } else {
        0pt
      },
      top: if (header_underline == true and y == 1) {
        frame_stroke + stroke_color
      } else {
        if y > 0 {
          if rows == true {
            inner_stroke + stroke_color
          } else {
            0pt
          }
        } else {
          if ends == true {
            frame_stroke + stroke_color
          } else {
            0pt
          }
        }
      },
      bottom: if ends == true {
        frame_stroke + stroke_color
      } else {
        0pt
      },
    )
  )
  set table(
    stroke: frame(),
    rows: 1.8em,
    // Header alignment is limited; see the Typst issue below.
    // https://github.com/typst/typst/issues/3734
    align: col_align,
    fill: (x, y) => if y == 0 and header_color != none {
      header_color
    } else if y == 0 and header_color == none { white } else if calc.even(y)
      and striping == "even" { fill } else if calc.odd(y)
      and striping == "odd" { fill } else { white },
  )
  // Style header cells by coordinates because table.header does not support these styles.
  show table.cell.where(y: 0): strong

  set par(justify: false)
  set text(font: font, weight: weight, stretch: 75%, size: raw_size)
  body
}
