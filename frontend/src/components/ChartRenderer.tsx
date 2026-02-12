import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import './ChartRenderer.css'

interface ChartRendererProps {
  config: {
    type: 'line' | 'bar'
    x: string
    y: string
    series?: string
    title?: string
  }
  data: any[]
}

export default function ChartRenderer({ config, data }: ChartRendererProps) {
  if (!data || data.length === 0) {
    return <div>No data to display</div>
  }

  // Transform data for Recharts
  // If series is specified, group by x-axis value and create separate series columns
  let chartData: any[]
  let seriesValues: string[] = []
  
  if (config.series) {
    // Get all unique series values
    seriesValues = Array.from(new Set(data.map(d => String(d[config.series!]))))
    
    // Group by x-axis value
    const grouped: Record<string, Record<string, any>> = {}
    
    data.forEach(row => {
      const xValue = String(row[config.x])
      const seriesValue = String(row[config.series!])
      const yValue = row[config.y]
      
      if (!grouped[xValue]) {
        grouped[xValue] = { [config.x]: xValue }
        // Initialize all series to 0
        seriesValues.forEach(s => {
          grouped[xValue][s] = 0
        })
      }
      
      grouped[xValue][seriesValue] = yValue
    })
    
    // Sort by x value (convert to number if possible)
    chartData = Object.values(grouped).sort((a, b) => {
      const aVal = Number(a[config.x]) || 0
      const bVal = Number(b[config.x]) || 0
      return aVal - bVal
    })
  } else {
    chartData = data.map(row => ({
      [config.x]: row[config.x],
      [config.y]: row[config.y]
    })).sort((a, b) => {
      const aVal = Number(a[config.x]) || 0
      const bVal = Number(b[config.x]) || 0
      return aVal - bVal
    })
  }
  
  // Generate consistent colors for series
  const colors = [
    '#58a6ff', '#3fb950', '#d29922', '#f78166', '#bc8cff',
    '#79c0ff', '#56d364', '#e3b341', '#ffa198', '#d2a8ff'
  ]

  const axisStyle = { fill: '#8b949e', fontSize: 12 }
  const gridColor = '#21262d'

  if (config.type === 'line') {
    return (
      <div className="chart-container">
        {config.title && <h4 className="chart-title">{config.title}</h4>}
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
            <XAxis dataKey={config.x} tick={axisStyle} stroke={gridColor} />
            <YAxis tick={axisStyle} stroke={gridColor} />
            <Tooltip contentStyle={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3' }} />
            {config.series ? (
              <>
                <Legend wrapperStyle={{ color: '#8b949e', fontSize: 12 }} />
                {seriesValues.map((series, idx) => (
                  <Line
                    key={series}
                    type="monotone"
                    dataKey={series}
                    stroke={colors[idx % colors.length]}
                    fill={colors[idx % colors.length]}
                    strokeWidth={2}
                    dot={false}
                  />
                ))}
              </>
            ) : (
              <Line type="monotone" dataKey={config.y} stroke={colors[0]} strokeWidth={2} dot={false} />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    )
  } else {
    return (
      <div className="chart-container">
        {config.title && <h4 className="chart-title">{config.title}</h4>}
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
            <XAxis dataKey={config.x} tick={axisStyle} stroke={gridColor} />
            <YAxis tick={axisStyle} stroke={gridColor} />
            <Tooltip contentStyle={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3' }} />
            {config.series ? (
              <>
                <Legend wrapperStyle={{ color: '#8b949e', fontSize: 12 }} />
                {seriesValues.map((series, idx) => (
                  <Bar
                    key={series}
                    dataKey={series}
                    fill={colors[idx % colors.length]}
                    radius={[3, 3, 0, 0]}
                  />
                ))}
              </>
            ) : (
              <Bar dataKey={config.y} fill={colors[0]} radius={[3, 3, 0, 0]} />
            )}
          </BarChart>
        </ResponsiveContainer>
      </div>
    )
  }
}

