# Write the S15 JLS copy from the raw bundle the Python stage writes (s15_har/method.py write_bundle).
# Julia Base and the Serialization stdlib only, so it runs without the package server.
#
#   julia s15_har/julia/write_jls.jl <bundle dir> <output .jls.gz>
#
# The file is a Dict{String,Any}:
#   "sets"       => Dict(set name => Vector{String}), lower case, as in gsdfset.har
#   "data"       => Dict(lower-case header => Array{Float64}), the 31 headers of gsdfdat.har
#   "parameters" => Dict(lower-case header => Array{Float64}), gsdfpar.har, with "rdlt" => Int
#   "dims"       => Dict(lower-case header => Vector{String}), the set of each axis
#   "meta"       => Dict("drel" => DREL elements, "julia" => VERSION string)
# serialized with Serialization, then gzip -9 -n (no name or time stamp, so two runs give the same bytes).
using Serialization

function read_bundle(dir)
    sets = Dict{String,Vector{String}}()
    drel = String[]
    for line in eachline(joinpath(dir, "sets.txt"))
        name, els = split(line, "|")
        if name == "DREL"
            drel = String.(split(els, ","))
        else
            sets[String(name)] = String.(split(els, ","))
        end
    end
    data = Dict{String,Any}()
    pars = Dict{String,Any}()
    dims = Dict{String,Vector{String}}()
    for line in eachline(joinpath(dir, "manifest.txt"))
        f = split(line, "|")
        if f[1] == "scalar"
            pars[lowercase(f[2])] = parse(Int, f[3])
            dims[lowercase(f[2])] = String[]
            continue
        end
        group, name, labs, shp = f
        shape = Tuple(parse.(Int, split(shp, ",")))
        arr = Array{Float64}(undef, shape)
        open(joinpath(dir, "$(name).f64"), "r") do io
            read!(io, arr)
        end
        arr .= ltoh.(arr)
        (group == "data" ? data : pars)[lowercase(name)] = arr
        dims[lowercase(name)] = String.(split(labs, ","))
    end
    return Dict{String,Any}("sets" => sets, "data" => data, "parameters" => pars, "dims" => dims,
        "meta" => Dict{String,Any}("drel" => drel, "julia" => string(VERSION)))
end

function main(dir, out)
    blob = read_bundle(dir)
    buf = IOBuffer()
    serialize(buf, blob)
    bytes = take!(buf)
    open(pipeline(`gzip -9 -n -c`, stdout = out), "w") do io
        write(io, bytes)
    end
    println("jls written: ", out, " (", length(bytes), " bytes before gzip; julia ", VERSION, ")")
end

main(ARGS[1], ARGS[2])
