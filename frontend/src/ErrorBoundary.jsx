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
    console.error('ErrorBoundary поймал ошибку:', error, info)
    // Опционально отправить на backend для логирования ошибок
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="card alert-error-card">
          <div className="alert-error-title">Ошибка в интерфейсе</div>
          <div className="alert-error-body">{String(this.state.error)}</div>
          <div className="alert-error-body" style={{ marginTop: 8 }}>Откройте консоль (F12) и проверьте логи ошибок.</div>
        </div>
      )
    }
    return this.props.children
  }
}
