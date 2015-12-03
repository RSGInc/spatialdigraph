import networkx
import shapely.geometry
import os.path
import fiona
import fiona.crs
import pyproj





class SpatialDiGraph(networkx.DiGraph):


    def coords(self, *nodes):
        if len(nodes) == 0:
            raise Exception('must provide at least one node')

        for nd in nodes:
            if nd not in self.node:
                raise Exception('{} is not a node in the graph'.format(nd))
            if 'coords' not in self.node[nd]:
                raise Exception('Node {} does not have a coords attribute'.format(nd))

        if len(nodes) > 1:
            for u,v in zip(nodes[:-1], nodes[1:]):
                if v not in self.edge[u]:
                    raise Exception('{} is not and edge in the graph'.format((u,v)))
                if 'coords' not in self.edge[u][v]:
                    raise Exception('Edge {} does not have a coords attribute'.format((u,v)))
        
        if len(nodes) == 1:
            return self.node[nodes[0]]['coords']
        else: 
            coords = [self.node[nodes[0]]['coords']]
            edges = zip(nodes[:-1], nodes[1:])
            for u,v in edges: 
                coords.extend(self.edge[u][v]['coords'])
                coords.append(self.node[v]['coords'])
            return coords




    def xy(self, *nodes):
        if len(nodes) == 1:
            return self.coords(*nodes)
        else:
            return zip(*self.coords(*nodes))

    def shape(self, *nodes):       
        if len(nodes) == 1:
            return shapely.geometry.Point(self.coords(*nodes))
        else:
            return shapely.geometry.LineString(self.coords(*nodes))

    
    def geometry(self, *nodes):
        return shapely.geometry.mapping(self.shape(*nodes))


    def feature(self, *nodes):
        if len(nodes) not in [1,2]:
            raise Exception('must provide either one or two nodes')

        if len(nodes) == 1:
            props = self.node[nodes[0]].copy()
            props['node'] = nodes[0]
        else:
            props = self.edge[nodes[0]][nodes[1]].copy()
            props['anode'] = nodes[0]
            props['bnode'] = nodes[1]

        geom = self.geometry(*nodes)

        return {'geometry':geom,
                'properties': props,
                'type': 'Feature'}
        

    @property
    def __geo_interface__(self):
        features = []

        for nd in self.node:
            features.append(self.feature(nd))
        for u,v in self.edges_iter():
            features.append(self.feature(u,v))

        return {'type':'FeatureCollection',
                'features': features}


    def crs(self):
        return self.graph['crs']

    def transform(self, crs):
        '''in place'''

        g = self
        
        p_in = pyproj.Proj(g.crs())
        p_out = pyproj.Proj(crs)

        for node_id in g.nodes_iter():
            g.node[node_id]['coords'] = pyproj.transform(p_in, p_out,
                                                         *g.node[node_id]['coords'])

        for u, v in g.edges_iter():
            if g[u][v]['coords']:
                g[u][v]['coords'] = zip(*pyproj.transform(p_in, p_out,
                                                          *zip(*g[u][v]['coords'])))

        g.graph['crs'] = crs

        return None

 
    def writeGisFile(self, path, driver, node_dtype = 'str', node_fields = None, edge_fields = None):
        '''
                
        
        '''

        if node_fields is None:
            node_fields = {}

        if edge_fields is None:
            edge_fields = {}
        
        try:
            for dtype in node_fields.values():
                fiona.prop_type(dtype)
            for dtype in edge_fields.values():
                fiona.prop_type(dtype)
            fiona.prop_type(node_dtype)
        except Exception as e:
            raise Exception('error converting dtype to python type', e)


        node_fields['node'] = node_dtype
        edge_fields['anode'] = node_dtype
        edge_fields['bnode'] = node_dtype
        
          
        with fiona.open(
            path,
            'w',
            layer = 'nodes',
            driver = driver,
            crs = self.graph['crs'],
            schema = {'geometry':'Point',
                      'properties':node_fields}) as c:

            for node in self.nodes_iter():

                geom = self.geometry(node)  

                props = {}

                for k, dtype in node_fields.items():
                    if k != 'node':
                        if self.node[node].get(k) is None:
                            props[k] = None
                        else:
                            props[k] = fiona.prop_type(dtype)(self.node[node][k])
                        
                props['node'] = fiona.prop_type(node_dtype)(node)
                
                c.write({'geometry':geom, 'properties':props})
                     

        


        with fiona.open(
            path,
            'w',
            layer = 'edges',
            driver = driver,
            crs = self.graph['crs'],
            schema = {'geometry':'LineString',
                      'properties':edge_fields}) as c:

            for u, v in self.edges_iter():

                geom = self.geometry(u, v)

                props = {}

                for k, dtype in edge_fields.items():
                    if k not in ['anode', 'bnode']:
                        if self.edge[u][v].get(k) is None:
                            props[k] = None
                        else:
                            props[k] = fiona.prop_type(dtype)(self.edge[u][v][k])
 
                            


                props.update({'anode':fiona.prop_type(node_dtype)(u),
                              'bnode':fiona.prop_type(node_dtype)(v)})

                c.write({'geometry':geom, 'properties':props})

                
        return None

    def draw(self, ax, node_args = {}, edge_args = {}):


        xs,ys = [],[]
        for nd in self.node:
            x,y = self.coords(nd)
            xs.append(x)
            ys.append(y)
            
        ax.scatter(xs,ys, **node_args)


        for u,v in self.edges_iter():
            x,y = self.xy(u,v)
            ax.plot(x,y, **edge_args)



def readGisFile(path, method, precision = None):

    if method not in ['byname','bylocation']:
        raise Exception('method must be either "byname" or "bylocation"')

    if method == 'bylocation':
        if precision is None:
            raise Exception('if method is "bylocation" then precision must be provided')

    g = SpatialDiGraph()


    def rnd(coords, precision = precision):
        return tuple(map(lambda x: round(x, precision), coords))


    with fiona.open(path, 'r', layer = 'nodes') as c:

        crs = c.crs

        for rec in c:
            props = rec['properties']
            coords = rec['geometry']['coordinates']
            props['coords'] = coords

            if method == 'byname':
                node = props['node']
            else:
                node= tuple(rnd(coords))

            props.pop('node')
            
            g.add_node(node, props)


    with fiona.open(path, 'r', layer = 'edges') as c:
        
        if c.crs != crs:
            raise Exception('node and edge data must have same projection')

        for rec in c:
            props = rec['properties']
            coords = rec['geometry']['coordinates'][1:-1]
            props['coords'] = coords

            if method == 'byname':
                anode = props['anode']
                bnode = props['bnode']

            else:
                anode = rnd(rec['geometry']['coordinates'][0])
                bnode = rnd(rec['geometry']['coordinates'][-1])

            props.pop('anode')
            props.pop('bnode')
            
            
            if (anode not in g.node) or (bnode not in g.node):
                if method == 'bylocation':
                    msg = ('An end point for edge {} is not close enough to '
                           'any node. (Precision is {})').format((anode, bnode), precision)
                    raise Exception(msg, anode, bnode, props)
                else:
                    msg = ('An end node for edge {} is not one of the nodes'
                           'in the node dataset.').format((anode, bnode))
                    raise Exception(msg, anode, bnode, props)
            
            

            g.add_edge(anode, bnode, props)       

    g.graph['crs'] = c.crs

    return g