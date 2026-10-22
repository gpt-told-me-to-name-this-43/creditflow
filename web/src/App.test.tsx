import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { App } from './App.tsx'

describe('App', () => {
  it('renders the product name', () => {
    expect(renderToStaticMarkup(<App />)).toContain('<h1>CreditFlow</h1>')
  })
})
