import { useEffect, useRef, useCallback } from 'react'
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  forceX,
  forceY,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from 'd3-force'
import { select, pointer } from 'd3-selection'


/* ---------- public types ---------- */

export interface GraphNode {
  id: string
  name: string
  type: string
  mentions: number
}

export interface GraphEdge {
  source: string
  target: string
  weight: number
}

interface Props {
  nodes: GraphNode[]
  edges: GraphEdge[]
  onSelectNode?: (node: GraphNode | null) => void
}

/* ---------- colours per entity type ---------- */

const TYPE_COLORS: Record<string, string> = {
  person: '#3b82f6',
  org: '#22c55e',
  organization: '#22c55e',
  location: '#ef4444',
  place: '#ef4444',
  date: '#f59e0b',
  event: '#8b5cf6',
  money: '#0891b2',
  phone: '#ec4899',
  email: '#6366f1',
}

function colorFor(type: string): string {
  return TYPE_COLORS[type.toLowerCase()] || '#94a3b8'
}

/* ---------- internal simulation types ---------- */

interface SimNode extends SimulationNodeDatum {
  id: string
  name: string
  type: string
  mentions: number
  radius: number
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  weight: number
}

/* ---------- component ---------- */

export default function EntityGraph({ nodes, edges, onSelectNode }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null)
  const simRef = useRef<ReturnType<typeof forceSimulation<SimNode>> | null>(null)

  /* Stable callback ref so we don't re-render on selection changes */
  const selectCb = useRef(onSelectNode)
  selectCb.current = onSelectNode

  const buildGraph = useCallback(() => {
    const svg = svgRef.current
    if (!svg || nodes.length === 0) return

    const width = svg.clientWidth || 800
    const height = svg.clientHeight || 600

    /* ---- prepare data (deep copy so d3 can mutate) ---- */
    const maxMentions = Math.max(...nodes.map(n => n.mentions), 1)
    const simNodes: SimNode[] = nodes.map(n => ({
      id: n.id,
      name: n.name ?? n.id,
      type: n.type,
      mentions: n.mentions,
      radius: 6 + (n.mentions / maxMentions) * 24,
    }))

    const nodeById = new Map(simNodes.map(n => [n.id, n]))
    const simLinks: SimLink[] = edges
      .filter(e => nodeById.has(e.source) && nodeById.has(e.target))
      .map(e => ({
        source: e.source,
        target: e.target,
        weight: e.weight,
      }))

    /* ---- d3 selection ---- */
    const sel = select(svg)
    sel.selectAll('*').remove()

    /* Container group for zoom/pan */
    const g = sel.append('g')

    /* Zoom behaviour via native wheel/pointer events (avoids importing d3-zoom) */
    let tx = 0, ty = 0, scale = 1
    function applyTransform() {
      g.attr('transform', `translate(${tx},${ty}) scale(${scale})`)
    }

    sel.on('wheel', (event: WheelEvent) => {
      event.preventDefault()
      const [mx, my] = pointer(event, svg)
      const k = event.deltaY < 0 ? 1.1 : 0.9
      tx = mx - k * (mx - tx)
      ty = my - k * (my - ty)
      scale *= k
      applyTransform()
    })

    /* Pan via pointer drag on background */
    let panning = false
    let panStartX = 0, panStartY = 0, panTx0 = 0, panTy0 = 0
    sel.on('pointerdown', (event: PointerEvent) => {
      if ((event.target as Element).tagName === 'svg' || (event.target as Element).tagName === 'SVG') {
        panning = true
        panStartX = event.clientX
        panStartY = event.clientY
        panTx0 = tx
        panTy0 = ty
        ;(event.target as Element).setPointerCapture(event.pointerId)
      }
    })
    sel.on('pointermove', (event: PointerEvent) => {
      if (!panning) return
      tx = panTx0 + (event.clientX - panStartX)
      ty = panTy0 + (event.clientY - panStartY)
      applyTransform()
    })
    sel.on('pointerup', () => { panning = false })

    /* ---- draw edges ---- */
    const maxWeight = Math.max(...simLinks.map(l => l.weight), 1)
    const linkSel = g
      .append('g')
      .attr('stroke', 'var(--border)')
      .selectAll('line')
      .data(simLinks)
      .join('line')
      .attr('stroke-opacity', 0.5)
      .attr('stroke-width', (d: SimLink) => 1 + (d.weight / maxWeight) * 3)

    /* ---- draw nodes ---- */
    const nodeSel = g
      .append('g')
      .selectAll<SVGCircleElement, SimNode>('circle')
      .data(simNodes)
      .join('circle')
      .attr('r', (d: SimNode) => d.radius)
      .attr('fill', (d: SimNode) => colorFor(d.type))
      .attr('stroke', '#fff')
      .attr('stroke-width', 1.5)
      .style('cursor', 'pointer')

    /* ---- draw labels ---- */
    const labelSel = g
      .append('g')
      .selectAll<SVGTextElement, SimNode>('text')
      .data(simNodes)
      .join('text')
      .text((d: SimNode) => d.name)
      .attr('font-size', 11)
      .attr('font-family', 'inherit')
      .attr('fill', 'var(--text)')
      .attr('text-anchor', 'middle')
      .attr('dy', (d: SimNode) => d.radius + 14)
      .style('pointer-events', 'none')
      .style('user-select', 'none')

    /* ---- click to select ---- */
    nodeSel.on('click', (_event: MouseEvent, d: SimNode) => {
      selectCb.current?.({ id: d.id, type: d.type, mentions: d.mentions })
    })

    /* Click background to deselect */
    sel.on('click', (event: MouseEvent) => {
      if ((event.target as Element).tagName === 'svg' || (event.target as Element).tagName === 'SVG') {
        selectCb.current?.(null)
      }
    })

    /* ---- drag (manual pointer events) ---- */
    let dragging: SimNode | null = null
    nodeSel.on('pointerdown', (event: PointerEvent, d: SimNode) => {
      event.stopPropagation()
      dragging = d
      d.fx = d.x
      d.fy = d.y
      simulation.alphaTarget(0.3).restart()
      ;(event.target as Element).setPointerCapture(event.pointerId)
    })
    nodeSel.on('pointermove', (event: PointerEvent) => {
      if (!dragging) return
      /* Convert from screen coords to graph coords (undo zoom transform) */
      const rect = svg.getBoundingClientRect()
      dragging.fx = (event.clientX - rect.left - tx) / scale
      dragging.fy = (event.clientY - rect.top - ty) / scale
    })
    nodeSel.on('pointerup', (_event: PointerEvent) => {
      if (!dragging) return
      simulation.alphaTarget(0)
      dragging.fx = null
      dragging.fy = null
      dragging = null
    })

    /* ---- force simulation ---- */
    const simulation = forceSimulation<SimNode>(simNodes)
      .force(
        'link',
        forceLink<SimNode, SimLink>(simLinks)
          .id(d => d.id)
          .distance(100),
      )
      .force('charge', forceManyBody().strength(-200))
      .force('center', forceCenter(width / 2, height / 2))
      .force('collide', forceCollide<SimNode>().radius(d => d.radius + 4))
      .force('x', forceX<SimNode>(width / 2).strength(0.04))
      .force('y', forceY<SimNode>(height / 2).strength(0.04))

    simulation.on('tick', () => {
      linkSel
        .attr('x1', (d: SimLink) => (d.source as SimNode).x ?? 0)
        .attr('y1', (d: SimLink) => (d.source as SimNode).y ?? 0)
        .attr('x2', (d: SimLink) => (d.target as SimNode).x ?? 0)
        .attr('y2', (d: SimLink) => (d.target as SimNode).y ?? 0)

      nodeSel.attr('cx', (d: SimNode) => d.x ?? 0).attr('cy', (d: SimNode) => d.y ?? 0)

      labelSel.attr('x', (d: SimNode) => d.x ?? 0).attr('y', (d: SimNode) => d.y ?? 0)
    })

    simRef.current = simulation

    return () => {
      simulation.stop()
    }
  }, [nodes, edges])

  /* Build / rebuild when data changes */
  useEffect(() => {
    const cleanup = buildGraph()
    return () => {
      cleanup?.()
      simRef.current?.stop()
    }
  }, [buildGraph])

  /* Rebuild on container resize */
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const ro = new ResizeObserver(() => {
      simRef.current?.stop()
      buildGraph()
    })
    ro.observe(svg)
    return () => ro.disconnect()
  }, [buildGraph])

  return (
    <svg
      ref={svgRef}
      style={{
        width: '100%',
        height: '100%',
        minHeight: 500,
        background: 'var(--bg)',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border)',
      }}
    />
  )
}
