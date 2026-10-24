import { useSuspenseQuery } from '@tanstack/react-query'
import { CheckIcon } from 'lucide-react'
import { type ReactNode, useId } from 'react'
import { creditProductsQuery } from '@/api/queries/products.ts'
import type { components } from '@/api/schema.d.ts'
import { Button } from '@/components/ui/button.tsx'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card.tsx'
import { constraintTexts, productTexts } from '@/content/wizard.ts'
import { formatMoney, formatRate } from '@/lib/money.ts'
import { cn } from '@/lib/utils.ts'
import { productParams } from './products.ts'
import type { Application } from './wizard-form.ts'

type CreditProduct = components['schemas']['CreditProduct']

interface StepProductProps {
  application: Application
  saving: boolean
  onChoose: (productId: string) => void
  onChangeTerms: () => void
  onNext: () => void
}

export function StepProduct({
  application,
  saving,
  onChoose,
  onChangeTerms,
  onNext,
}: StepProductProps) {
  const { data: products } = useSuspenseQuery(creditProductsQuery(productParams(application)))
  const suitable = products.filter((product) => product.suitable)
  const unsuitable = products.filter((product) => !product.suitable)
  const chosen = suitable.find((product) => product.id === application.product_id)
  const titleId = useId()
  const disclaimer = products[0]?.disclaimer

  return (
    <section className="grid gap-8" aria-labelledby={titleId}>
      <div className="grid gap-2">
        <h2 id={titleId} className="text-2xl font-bold">
          {productTexts.title}
        </h2>
        <p className="text-muted-foreground">{productTexts.description}</p>
      </div>

      {suitable.length > 0 ? (
        <div className="grid gap-3">
          <h3 className="text-lg font-semibold">{productTexts.suitable}</h3>
          <ul className="grid grid-cols-2 gap-4" aria-label={productTexts.suitable}>
            {suitable.map((product) => (
              <li key={product.id}>
                <ProductCard
                  product={product}
                  action={
                    product.id === chosen?.id ? (
                      <p className="flex items-center gap-2 font-semibold">
                        <CheckIcon aria-hidden className="size-4" />
                        {productTexts.chosen}
                      </p>
                    ) : (
                      <Button
                        type="button"
                        size="lg"
                        disabled={saving}
                        onClick={() => onChoose(product.id)}
                        aria-label={`${productTexts.choose}: ${product.name}`}
                      >
                        {productTexts.choose}
                      </Button>
                    )
                  }
                />
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p role="status" className="text-lg font-medium">
          {productTexts.none}
        </p>
      )}

      {unsuitable.length > 0 && (
        <div className="grid gap-3">
          <h3 className="text-lg font-semibold text-muted-foreground">{productTexts.unsuitable}</h3>
          <ul className="grid grid-cols-2 gap-4" aria-label={productTexts.unsuitable}>
            {unsuitable.map((product) => (
              <li key={product.id}>
                <ProductCard
                  product={product}
                  muted
                  action={
                    <Button type="button" variant="outline" onClick={onChangeTerms}>
                      {productTexts.changeTerms}
                    </Button>
                  }
                />
              </li>
            ))}
          </ul>
        </div>
      )}

      {disclaimer && <p className="text-sm text-muted-foreground">{disclaimer}</p>}

      <div className="flex gap-3">
        <Button type="button" variant="outline" size="lg" onClick={onChangeTerms}>
          {productTexts.changeTerms}
        </Button>
        {chosen && (
          <Button type="button" size="lg" onClick={onNext}>
            {productTexts.next}
          </Button>
        )}
      </div>
    </section>
  )
}

function ProductCard({
  product,
  muted,
  action,
}: {
  product: CreditProduct
  muted?: boolean
  action: ReactNode
}) {
  return (
    <Card className={cn('h-full', muted && 'bg-muted text-muted-foreground')}>
      <CardHeader>
        <CardTitle className="text-xl">{product.name}</CardTitle>
      </CardHeader>
      <CardContent className="grid flex-1 gap-4">
        {product.monthly_payment_rub && (
          <div className="grid gap-1">
            <p className="text-sm text-muted-foreground">{productTexts.payment}</p>
            <p className="text-2xl font-bold">{formatMoney(product.monthly_payment_rub)}</p>
          </div>
        )}
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
          <dt className="text-muted-foreground">{productTexts.rate}</dt>
          <dd>{formatRate(product.annual_rate_pct)}</dd>
          <dt className="text-muted-foreground">{productTexts.amountRange}</dt>
          <dd>
            {formatMoney(product.min_amount_rub, { kopecks: false })} –{' '}
            {formatMoney(product.max_amount_rub, { kopecks: false })}
          </dd>
          <dt className="text-muted-foreground">{productTexts.termRange}</dt>
          <dd>
            {product.min_term_months}–{product.max_term_months} мес.
          </dd>
        </dl>
        {product.unmet_constraints.length > 0 && (
          <ul className="grid list-disc gap-1 pl-5 text-sm font-medium text-foreground">
            {product.unmet_constraints.map((code) => (
              <li key={code}>{constraintTexts[code]}</li>
            ))}
          </ul>
        )}
      </CardContent>
      <CardFooter>{action}</CardFooter>
    </Card>
  )
}
