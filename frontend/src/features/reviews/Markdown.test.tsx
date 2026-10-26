import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Markdown } from './Markdown'

// each item's own text, without its nested list
const lis = (list: Element) => Array.from(list.children).map((li) =>
  Array.from(li.childNodes).filter((n) => n.nodeName !== 'DIV').map((n) => n.textContent).join('').trim())

describe('Markdown lists', () => {
  it('nests indented items under the item above', () => {
    const { container } = render(<Markdown text={[
      '- **Architecture**: two models',
      '  - **Small**: 6 layers',
      '  - **Large**: 12 layers',
      '- **Tokenizer**: Unigram',
    ].join('\n')} />)
    const top = container.querySelector('ul')!
    expect(lis(top)).toEqual(['Architecture: two models', 'Tokenizer: Unigram'])
    const inner = top.querySelector('li ul')!
    expect(lis(inner)).toEqual(['Small: 6 layers', 'Large: 12 layers'])
    expect(container.querySelectorAll('p')).toHaveLength(0)
  })

  it('keeps a numbered list whole across blank lines, with numbered or bulleted children', () => {
    const { container } = render(<Markdown text={'1. First\n   - detail\n\n2. Second\n   continued\n\nAfter.'} />)
    const ol = container.querySelector('ol')!
    expect(container.querySelectorAll('ol')).toHaveLength(1)
    expect(lis(ol)).toEqual(['First', 'Second continued'])
    expect(ol.querySelector('ul')!.textContent).toBe('detail')
    expect(container.querySelector('p')!.textContent).toBe('After.')
  })

  it('starts a numbered list at its first number', () => {
    const { container } = render(<Markdown text={'3. Third\n4. Fourth'} />)
    expect(container.querySelector('ol')!.getAttribute('start')).toBe('3')
  })
})
