import { Component, type ReactNode } from 'react'

/** One panel that cannot read its data shows a note; the rest of the page keeps working. */
export class Guard extends Component<{ what: string; children: ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null }
  static getDerivedStateFromError(err: Error) { return { err } }
  componentDidCatch(err: Error) { console.warn(`[wardlight] ${this.props.what}:`, err.message) }
  render() {
    if (this.state.err) return <div className="empty" role="status">{this.props.what} could not be shown from this data version. The other panels are unaffected.</div>
    return this.props.children
  }
}
