# Model-run preparation of an aggregated data base for GlobalTradeAnalysisProjectModelV7 (levels form).
#
# The Julia port writes each Armington nest as log(q_dom), log(q_imp) .== log(ces(...)) for every agent with
# purchases of the composite, so an agent that buys a commodity only from domestic producers or only from
# imports gives log(0) and Ipopt stops on an invalid number. GEMPACK's linear form has no such problem, and
# the GTAP data base has no such cells (every firm cell is either zero or positive on both sides). This data base keeps the structural zeros of the source tables (S13 FIT), so an
# aggregation can have such cells.
#
# armington_swap! gives each such agent a small amount of the missing side by swapping it with the agent
# of the same commodity and region that buys most of the missing side: agent i gives eps of its only side and takes eps of the
# other; donor k does the opposite. Region totals of domestic and imported purchases at basic prices are
# unchanged (market clearing holds), and so is each agent's total at basic and at purchasers' prices. Each agent
# moves both sides at its own power on that side, so tax revenue is unchanged too (measured at 1.5e-11 on the
# smoke map, S15 QA N1); the donor's average powers shift by at most a few 1e-7. eps is SHARE times the agent's purchases, at most half of what the donor holds.
# The data base itself is not changed: this runs on the aggregated copy in memory (choice model_run_prep).
using NamedArrays

const SHARE = 1e-6

function armington_swap!(hData)
    agents = Tuple{String,String,Union{Nothing,String}}[]
    acts = names(hData["vdfb"], 2)
    for a in acts
        push!(agents, ("vdf", "vmf", a))
    end
    push!(agents, ("vdp", "vmp", nothing), ("vdg", "vmg", nothing), ("vdi", "vmi", nothing))
    comm = names(hData["vdfb"], 1)
    reg = names(hData["vdfb"], 3)
    get(k, a, c, r) = a === nothing ? hData[k][c, r] : hData[k][c, a, r]
    function add!(k, a, c, r, v)
        if a === nothing
            hData[k][c, r] += v
        else
            hData[k][c, a, r] += v
        end
    end
    n = 0
    moved = 0.0
    for r in reg, c in comm
        for (d, m, a) in agents
            db, mb = get(d * "b", a, c, r), get(m * "b", a, c, r)
            (db > 0) == (mb > 0) && continue
            only, other = db > 0 ? (d, m) : (m, d)
            total = db + mb
            power = get(only * "p", a, c, r) / get(only * "b", a, c, r)
            # donor: the agent with the most of the missing side
            best, bestv = nothing, 0.0
            for (d2, m2, a2) in agents
                (d2, a2) == (d, a) && continue
                v = get((other == d ? d2 : m2) * "b", a2, c, r)
                if v > bestv
                    best, bestv = (d2, m2, a2), v
                end
            end
            # A region with no purchases of the missing side at all (332 commodity-region pairs in the full data base,
            # e.g. coa in ARE: no domestic output) has no donor; a map that keeps such a pair needs it pooled.
            best === nothing && error("no donor for $c in $r: the region has no $(other == d ? "domestic" : "imported") purchases of $c by any agent; pool $c or $r on this map")
            (d2, m2, a2) = best
            o2, s2 = other == d ? (d2, m2) : (m2, d2)
            eps = min(SHARE * total, 0.5 * bestv)
            p2 = get(o2 * "p", a2, c, r) / get(o2 * "b", a2, c, r)
            add!(only * "b", a, c, r, -eps); add!(only * "p", a, c, r, -eps * power)
            add!(other * "b", a, c, r, eps); add!(other * "p", a, c, r, eps * power)
            add!(o2 * "b", a2, c, r, -eps); add!(o2 * "p", a2, c, r, -eps * p2)
            add!(s2 * "b", a2, c, r, eps); add!(s2 * "p", a2, c, r, eps * p2)
            n += 1
            moved += eps
        end
    end
    return n, moved
end

# Zero-weight parameter cells (beta v4, S16 2026-10-26). aggregate_data averages each parameter over the members of a
# (commodity group, region group) cell weighted by the cell's flows. A cell whose weights sum to 0 comes out 0/0 = NaN:
# BFA and KEN (and the other no-refinery regions) have no crude flows at all, so with crude as its own sector and the
# region alone in its group SUBP, INCP, ESBV, ESBM, ESBD, ESBQ, ESBT, ESBC and ETRQ are NaN for (oil, region) and the
# package stops on fix(NaN). fill_zero_weight_parameters! sets each such cell to the unweighted mean of the members'
# values (for a single-member group, the member's own value). The cell carries no flows, so the model is unchanged;
# every other cell is left bit-identical. Users of their own aggregation tools need the same fallback (README).
const ZERO_WEIGHT_SOURCE = Dict("esbc" => "esbt")      # the package aggregates esbc from the esbt values

function _dim_map(maps, elems)
    for m in maps
        Set(names(m, 1)) == Set(elems) && return m
    end
    return nothing                                       # a set the map leaves as it is (marg)
end

function fill_zero_weight_parameters!(hParAgg, hPar, maps)
    filled = Tuple{String,Vector{String},Float64}[]
    for k in sort(collect(keys(hParAgg)))
        v = hParAgg[k]
        (v isa NamedArray && eltype(v) <: AbstractFloat && any(isnan, v)) || continue
        src = hPar[get(ZERO_WEIGHT_SOURCE, k, k)]
        ndims(src) == ndims(v) || continue
        dmaps = [_dim_map(maps, names(src, d)) for d in 1:ndims(src)]
        for I in findall(isnan, Array(v))
            g = [names(v, d)[I[d]] for d in 1:ndims(v)]
            members = [dmaps[d] === nothing ? findall(==(g[d]), names(src, d)) :
                       findall(==(g[d]), Array(dmaps[d])) for d in 1:ndims(v)]
            vals = [Float64(src[J...]) for J in Iterators.product(members...)]
            vals = filter(isfinite, vals)
            isempty(vals) && continue
            x = sum(vals) / length(vals)
            v[I] = x
            push!(filled, (k, g, x))
        end
    end
    return filled
end
