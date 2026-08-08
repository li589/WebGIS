import { describe, expect, it } from 'vitest'

import { buildJobLayer } from '@/stores/layers/result-adapter'

describe('result-adapter analysis charts/tables', () => {
  it('extracts chart and table refs into job layer fields', async () => {
    const job = await buildJobLayer(
      {
        run_id: 'run-abc12345',
        command_type: 'analysis',
        status: 'succeeded',
        progress: 100,
        created_at: '2026-08-05T00:00:00Z',
        updated_at: '2026-08-05T00:00:01Z',
        message: 'ok',
        result_refs: [
          {
            result_id: 'chart-1',
            result_kind: 'chart',
            title: 'Analysis Chart: hist',
            mime_type: 'application/json',
            inline_data: {
              chart_type: 'histogram',
              title: 'Histogram',
              x_label: 'value',
              y_label: 'count',
              series: [{ name: 'count', x: [0.5, 1.5], y: [2, 5] }],
            },
            updated_at: '2026-08-05T00:00:01Z',
          },
          {
            result_id: 'table-1',
            result_kind: 'table',
            title: 'Analysis Table: hist',
            mime_type: 'application/json',
            inline_data: {
              title: 'Bins',
              columns: ['center', 'count'],
              rows: [
                [0.5, 2],
                [1.5, 5],
              ],
            },
            updated_at: '2026-08-05T00:00:01Z',
          },
        ],
      } as never,
      'Test Layer',
    )
    expect(job.analysisCharts?.length).toBe(1)
    expect(job.analysisCharts?.[0].chartType).toBe('histogram')
    expect(job.analysisCharts?.[0].series[0].y).toEqual([2, 5])
    expect(job.analysisTables?.length).toBe(1)
    expect(job.analysisTables?.[0].columns).toEqual(['center', 'count'])
  })
})
