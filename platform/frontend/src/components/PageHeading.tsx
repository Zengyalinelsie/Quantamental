import type { ReactNode } from 'react'

interface PageHeadingProps {
  title: string
  description: string
  eyebrow?: string
  extra?: ReactNode
}

export function PageHeading({ title, description, eyebrow, extra }: PageHeadingProps) {
  return (
    <header className="pageHeading">
      <div>
        {eyebrow ? <p className="pageHeading__eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
        <p className="pageHeading__description">{description}</p>
      </div>
      {extra ? <div className="pageHeading__extra">{extra}</div> : null}
    </header>
  )
}
