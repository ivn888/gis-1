import numpy as np
import pandas as pd
import sys

g = np.random.uniform(300,500,1000000).reshape(1000,1000)

class d8():
        
    def __init__(self, data, data_type='dem', input_type='ascii', band=1, nodata=0, pour=9, bbox=None, autorun=False):

        if input_type == 'ascii':
            pass

	if input_type == 'raster':
	    import rasterio
	    f = rasterio.open(data)
            self.crs = f.crs
            self.bbox = tuple(f.bounds)
            self.shape = f.shape
            self.fill = f.nodatavals[0]
	    if len(f.indexes) > 1:
	        self.data = np.ma.filled(f.read_band(band))
	    else:
	        self.data = np.ma.filled(f.read())
            f.close()
            self.data = self.data.reshape(self.shape)

        if input_type == 'array':
            self.data = data
            self.shape = data.shape
            if bbox:
                self.bbox = bbox
            else:
                self.bbox = (0, 0, data.shape[0], data.shape[1])
        
        self.shape_min = np.min_scalar_type(max(self.data.shape))
        self.size_min = np.min_scalar_type(self.data.size)
        self.pour = pour
        self.nodata = nodata    
        self.idx = np.indices(self.data.shape, dtype=self.shape_min)

        if autorun == True:
            if input_type == 'dem':
                self.d = self.flowdir(data)
            elif input_type == 'flowdir':
                self.d = data

            self.branches, self.pos = self.prep_accum()
            self.accumulation = self.accum()
            self.catchment = self.catch()

    def update_progress(progress):
        sys.stdout.write('\r[{0}] {1}%'.format('#'*(progress/10), progress))

    def clip_array(self, new_bbox, inplace=False):
        df = pd.DataFrame(self.data,
                          index=np.linspace(b.bbox[1], b.bbox[3],
                                b.shape[0], endpoint=False),
                          columns=np.linspace(b.bbox[0], b.bbox[2],
                                b.shape[1], endpoint=False))
        df = df.loc[new_bbox[1]:new_bbox[3], new_bbox[0]:new_bbox[2]]

        if inplace == False:
            return df

        else:
            self.data = df.values
            self.bbox = new_bbox
            self.shape = self.data.shape

    def flowdir(self): 

        #corners
        c = {
        'nw' : {'k' : tuple(self.idx[:,0,0]),
	        'v' : [[0,1,1], [1,1,0]],
		'pad': np.array([3,4,5])},
        'ne' : {'k' : tuple(self.idx[:,0,-1]),
	        'v' : [[1,1,0], [-1,-2,-2]],
		'pad': np.array([5,6,7])},
        'sw' : {'k' : tuple(self.idx[:,-1,0]),
	        'v' : [[-2,-2,-1], [0,1,1]],
		'pad': np.array([1,2,3])},
        'se' : {'k' : tuple(self.idx[:,-1,-1]),
	        'v' : [[-1,-2,-2], [-2,-2,-1]],
		'pad': np.array([7,8,1])}
        }
    
        #edges
        edge = {
        'n' : {'k' : tuple(self.idx[:,0,1:-1]),
	       'pad' : np.array([3,4,5,6,7])},
        'w' : {'k' : tuple(self.idx[:,1:-1,0]),
	       'pad' : np.array([1,2,3,4,5])},
        'e' : {'k' : tuple(self.idx[:,1:-1,-1]),
	       'pad' : np.array([1,5,6,7,8])},
        's' : {'k' : tuple(self.idx[:,-1,1:-1]),
	       'pad' : np.array([1,2,3,7,8])}
        }
    
        #body
        body = self.idx[:, 1:-1, 1:-1]
    
        #output
        outmap = np.zeros(self.data.shape, dtype=np.int8)
    
    
        def select_surround(i, j):
            return ([i-1, i-1, i+0, i+1, i+1, i+1, i+0, i-1],
                   [j+0, j+1, j+1, j+1, j+0, j-1, j-1, j-1])
    
    
        def select_edge_sur(k):
            i,j = edge[k]['k']
            if k == 'n':
                return [i+0, i+1, i+1, i+1, i+0], [j+1, j+1, j+0, j-1, j-1]
            elif k =='e':
                return [i-1, i+1, i+1, i+0, i-1], [j+0, j+0, j-1, j-1, j-1]
            elif k =='s':
                return [i-1, i-1, i+0, i+0, i-1], [j+0, j+1, j+1, j-1, j-1]
            elif k == 'w':
                return [i-1, i-1, i+0, i+1, i+1], [j+0, j+1, j+1, j+1, j+0]
    
        # FILL CORNERS
        for i in c.keys():
            dat = self.data[c[i]['k']]
            sur = self.data[c[i]['v']]
            if ((dat - sur) > 0).any():
                outmap[c[i]['k']] = c[i]['pad'][np.argmax(dat - sur)]
            else:
                outmap[c[i]['k']] = self.nodata
    
        # FILL BODY
        for i, j in np.nditer(tuple(body), flags=['external_loop']):
            dat = self.data[i,j]
            sur = self.data[select_surround(i,j)]
            a = ((dat - sur) > 0).any(axis=0)
            b = np.argmax((dat - sur), axis=0) + 1
            c = self.nodata
            outmap[i,j] = np.where(a,b,c)
    
        #FILL EDGES
        for x in edge.keys():
            dat = self.data[edge[x]['k']]
            sur = self.data[select_edge_sur(x)]
            a = ((dat - sur) > 0).any(axis=0)
            b = edge[x]['pad'][np.argmax((dat - sur), axis=0)]
            c = self.nodata
            outmap[edge[x]['k']] = np.where(a,b,c)
    
        return outmap

    def prep_accum(self):

        coverage = np.full(self.d.size, np.iinfo(self.size_min).max, dtype=self.size_min)
        self.d = self.d.ravel()
        outer = pd.Series(index=np.arange(self.d.size,
                                          dtype=self.size_min)).apply(lambda x: [])

        def goto_cell_r(i):
            inner.append(i)
            dirs = [[0,0], [-1,0], [-1,1], [0,1], [1,1],
            [1,0], [1,-1], [0,-1], [-1,-1]]
            move = dirs[self.d[i]]
            next_i = i + move[1] + move[0]*self.shape[1]
            if self.d[i] == self.nodata:
                return i
#            elif (next_cell < 0).any(): #SHOULD ALSO ACCOUNT FOR N > SHAPE[0], SHAPE[1]
#                return i
            elif coverage[next_i] == next_i:
                return next_i
            else:
                coverage[next_i] = next_i
                return goto_cell_r(next_i)

        def pad_inner(lst, dtype=np.int64):
            inner_max_len = max(map(len, lst))
            result = np.full([len(lst), inner_max_len],
                              np.iinfo(self.size_min).max, dtype=self.size_min)
            for i, row in enumerate(lst):
                for j, val in enumerate(row):
                    result[i][j] = val
            return result
        
        def pad_outer(a):
            b = a.copy()
            f = np.vectorize(lambda x: x.shape[1])
            ms = f(b).max()
#            print ms
            for i in range(len(b)):
                b[i] = np.pad(
            b[i],
            ((0,0), (0, ms-b[i].shape[1])),
            mode='constant',
            constant_values = np.iinfo(self.size_min).max)
            return np.vstack(b)

        for w in outer.index:
            if coverage[w] != w:
                inner = []
                coverage[w] = w
                if self.d[w] != self.nodata:
                    h = goto_cell_r(w)
#                    print w
                    inner = np.array(inner)
                    inner = inner[np.where(inner != h)] #EXPENSIVE
                    outer[h].append(inner)
        
        outer = outer.apply(np.array)
        outer = outer[outer.str.len() > 0]

        self.d = self.d.reshape(self.shape)

        return (outer.apply(np.concatenate),
                pad_outer(np.array([pad_inner(i) for i in outer.values])).astype(self.size_min))

    def accum(self):

        if not hasattr(self, 'd'):
            self.d = self.flowdir()

        iterange = pd.Series(np.arange(self.d.size, dtype=self.size_min))

        if (not hasattr(self, 'branches')) or (not hasattr(self, 'pos')):
            self.branches, self.pos = self.prep_accum()

        def recursive_inter(arr):
            self.outer_s = pd.Series(np.zeros(arr.size), index=arr.index)

            def ret_branches(x):
                i = np.in1d(x.values, self.branches.index.values)
                if i.any():
                    retseries = self.branches[x.values[i]]
                    lenseries = retseries.apply(len)
                    self.outer_s = self.outer_s + lenseries.reindex(self.outer_s.index).fillna(0)
                    return ret_branches(pd.Series(np.concatenate(retseries.dropna().values), index=retseries.index.values.repeat(lenseries)))
            ret_branches(arr)

            return self.outer_s

        self.u = np.unique(self.pos[self.pos != np.iinfo(self.size_min).max]) 
        
        primary =  iterange[~(iterange.isin(self.branches.index.values))
                            & (iterange.isin(self.u))]
        intermediate = iterange[(iterange.isin(self.branches.index.values))
                            & (iterange.isin(self.u))]
        terminal = iterange[(iterange.isin(self.branches.index.values))
                            & ~(iterange.isin(self.u))]
        noflow = iterange[~(iterange.isin(self.branches.index.values))
                            & ~(iterange.isin(self.u))]
        del iterange

        intermediate = recursive_inter(intermediate)

        primary[:] = 0
        noflow[:] = 0

        for i in range(self.pos.shape[1]):
            primary = primary + np.where(np.in1d(primary.index.values, self.pos[:,i]), i, 0)
            intermediate = intermediate + np.where(np.in1d(intermediate.index.values, self.pos[:,i]), i, 0)


        upcells = pd.concat([primary, intermediate]).sort_index()

        # def recursive_(src):
        #     termsel = self.branches[terminal.values]
        #     termidx = np.repeat(termsel.index.values, termsel.apply(len).values)
        #     termsel = np.concatenate(termsel.values)
        #     term_in = np.where(np.in1d(termsel, self.branches.index.values))
        #     upcells = self.branches[termsel[term_in]].apply(len).values

        #     s1 = pd.Series(np.ones(termsel.size), index=termidx).reset_index().groupby('index').count()[0]
        #     s2 = pd.Series(upcells, index=termidx[term_in]).reset_index().groupby('index').sum()[0].reindex(s1.index).fillna(0)
        #     terminal = s1 + s2
        #     return terminal

        # terminal = recursive_(terminal)
        
        termvals = self.branches[terminal.values]
        term = pd.Series(np.concatenate(termvals.values), np.repeat(terminal.index.values, termvals.apply(len)))
        term = term.map(upcells).reset_index().groupby('index').sum()[0].sort_index()
        termvals = termvals.apply(len).sort_index()

        terminal = termvals + term

        iterange = pd.concat([upcells, terminal, noflow]).sort_index().values

        return iterange.reshape(self.d.shape)

    def catch(self, n):

        if not hasattr(self, 'd'):
            self.d = self.flowdir()

        iterange = np.arange(self.d.size) 

        if (not hasattr(self, 'branches')) or (not hasattr(self, 'pos')):
            self.branches, self.pos = self.prep_accum()

        if isinstance(n, int):
            pass
        elif isinstance(n, (tuple, list, np.ndarray)):
            n = n[0] + n[1]*self.d.shape[1]

        self.k = self.branches.index.values
        self.u = np.unique(self.pos)

        def get_catchment(n):
            # PRIMARY
            if (not n in self.k) and (n in self.u):
                q = np.where(self.pos==n)
                return self.pos[q[0], :q[1]]
            # INTERMEDIATE
            elif (n in self.k) and (n in self.u):
                prim = self.branches[n]
                q = np.where(self.pos==n)
                sec = self.pos[q[0], :q[1]]
                return np.concatenate([prim.ravel(), sec.ravel()])
            # FINAL
            elif (n in self.k) and (not n in self.u):
                upcells = self.branches[n]
                if np.in1d(upcells, self.k).any():
                    sec = np.concatenate(self.branches.loc[upcells].dropna().values)
                    return np.concatenate([upcells.ravel(), sec.ravel()])
                else:
                    return upcells.ravel()
    
        catchment = np.where(np.in1d(iterange, get_catchment(n)),
                             self.d.ravel(), self.nodata)
        catchment[n] = self.pour
        return catchment.reshape(self.d.shape)
