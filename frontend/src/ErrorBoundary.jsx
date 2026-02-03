import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    console.error('ErrorBoundary caught:', error, info)
    // Optionally send to backend logging endpoint
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="card" style={{borderLeft: '4px solid #ef4444', padding: 12, background: '#fff8f8'}}>
          <div style={{fontWeight:700,color:'#b91c1c'}}>Ошибка в интерфейсе</div>
          <div style={{marginTop:6,color:'#374151',fontSize:13}}>{String(this.state.error)}</div>
          <div style={{marginTop:8,fontSize:13,color:'#374151'}}>Откройте консоль (F12) и пришлите логи или разрешите мне отправить их на сервер.</div>
        </div>
      )
    }
    return this.props.children
  }
}
