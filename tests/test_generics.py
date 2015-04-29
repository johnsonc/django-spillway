import json
import io
import zipfile

from django.contrib.gis import geos
from django.test import TestCase
from greenwich.raster import Raster
from rest_framework import status
from rest_framework.test import APIRequestFactory

from spillway import generics, forms
from spillway.renderers import GeoJSONRenderer
from .models import GeoLocation, Location, RasterStore
from .test_serializers import RasterStoreTestBase, LocationFeatureSerializer

factory = APIRequestFactory()


class PaginatedGeoListView(generics.GeoListView):
    paginate_by_param = 'page_size'
    paginate_by = 10


class GeoDetailViewTestCase(TestCase):
    model = GeoLocation
    precision = forms.GeometryQueryForm()['precision'].field.initial

    def setUp(self):
        self.view = generics.GeoDetailView.as_view(model=self.model)
        self.pk = 1
        self.url = '/%d/' % self.pk
        self.radius = 5
        self.model.add_buffer((10, -10), self.radius)
        self.model.create()
        self.qs = self.model.objects.all()

    def test_json_response(self):
        expected = json.loads(self.qs[0].geom.geojson)
        response = self.view(factory.get(self.url), pk=self.pk).render()
        self.assertEqual(response.status_code, 200)
        feature = json.loads(response.content)
        self.assertEqual(feature['geometry'], expected)
        self.assertEqual(feature['type'], 'Feature')

    def test_geojson_response(self):
        expected = json.loads(
            self.qs.geojson(precision=self.precision)[0].geojson)
        request = factory.get(self.url, {'format': 'geojson'})
        with self.assertNumQueries(1):
            response = self.view(request, pk=self.pk).render()
        self.assertEqual(response.status_code, 200)
        feature = json.loads(response.content)
        self.assertEqual(feature['geometry'], expected)
        self.assertEqual(feature['type'], 'Feature')

    def test_kml_response(self):
        request = factory.get(self.url, {'format': 'kml'})
        response = self.view(request, pk=self.pk).render()
        part = self.qs.kml(precision=self.precision)[0].kml
        self.assertInHTML(part, response.content, count=1)


class GeoManagerDetailViewTestCase(GeoDetailViewTestCase):
    model = Location

    def test_simplify(self):
        request = factory.get(self.url, {'simplify': self.radius,
                                         'format': 'geojson'})
        response = self.view(request, pk=self.pk).render()
        orig = self.qs.get(pk=self.pk).geom
        serializer = LocationFeatureSerializer(
            data=json.loads(response.content))
        self.assertTrue(serializer.is_valid())
        self.assertLess(serializer.object.geom.num_coords, orig.num_coords)
        self.assertNotEqual(serializer.object.geom, orig)
        self.assertEqual(serializer.object.geom.srid, orig.srid)


class GeoListViewTestCase(TestCase):
    def setUp(self):
        self.srid = Location.geom._field.srid
        self.view = generics.GeoListView.as_view(model=Location)
        records = [{'name': 'Banff', 'coordinates': [-115.554, 51.179]},
                   {'name': 'Jasper', 'coordinates': [-118.081, 52.875]}]
        for record in records:
            obj = Location.add_buffer(record.pop('coordinates'), 0.5, **record)
        self.qs = Location.objects.all()

    def _parse_collection(self, response, srid=None):
        data = json.loads(response.content)
        self.assertEqual(data['type'], 'FeatureCollection')
        self.assertEqual(len(data['features']), len(self.qs))
        for feature in data['features']:
            yield geos.GEOSGeometry(
                json.dumps(feature['geometry']), srid or self.srid)

    def test_list(self):
        request = factory.get('/')
        response = self.view(request)
        self.assertEqual(len(response.data['features']), len(self.qs))

    def test_bounding_box(self):
        bbox = self.qs[0].geom.extent
        request = factory.get('/', {'bbox': ','.join(map(str, bbox))})
        response = self.view(request)
        self.assertEqual(len(response.data['features']), 1)

    def test_spatial_lookup(self):
        centroid = Location.objects.centroid()[0].centroid.geojson
        request = factory.get('/', {'intersects': centroid})
        response = self.view(request)
        self.assertEqual(len(response.data['features']), 1)

    def test_spatial_lookup_notfound(self):
        request = factory.get('/', {'intersects': 'POINT(0 0)'})
        response = self.view(request)
        self.assertEqual(len(response.data['features']), 0)

    def test_geojson(self):
        request = factory.get('/', {'format': 'geojson'})
        self.assertIsInstance(self.view(request).accepted_renderer,
                              GeoJSONRenderer)
        request = factory.get('/', HTTP_ACCEPT=GeoJSONRenderer.media_type)
        response = self.view(request).render()
        self.assertIsInstance(response.accepted_renderer, GeoJSONRenderer)
        for geom, obj in zip(self._parse_collection(response), self.qs):
            self.assertTrue(geom.equals_exact(obj.geom, 0.0001))

    def test_simplify(self):
        srid = 3857
        for format in 'json', 'geojson':
            request = factory.get('/', {'simplify': 10000, 'srs': srid,
                                        'format': format})
            response = self.view(request).render()
            for geom, obj in zip(self._parse_collection(response, srid), self.qs):
                orig = obj.geom.transform(srid, clone=True)
                self.assertNotEqual(geom, orig)
                self.assertLess(geom.num_coords, orig.num_coords)
        self.assertContains(response, 'EPSG::%d' % srid)


class GeoListCreateAPIView(TestCase):
    def setUp(self):
        self.view = generics.GeoListCreateAPIView.as_view(model=Location)
        Location.create()
        self.qs = Location.objects.all()

    def test_post(self):
        fs = LocationFeatureSerializer(self.qs, many=True)
        request = factory.post('/', fs.data, format='json')
        with self.assertNumQueries(1):
            response = self.view(request).render()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created = self.qs.get(pk=2)
        self.assertEqual(created.name, 'Vancouver')
        self.assertEqual(created.geom, fs.object[0].geom)


class PaginatedGeoListViewTestCase(TestCase):
    def setUp(self):
        self.view = PaginatedGeoListView.as_view(model=Location)
        for i in range(20): Location.create()
        self.qs = Location.objects.all()

    def _test_paginate(self, params, **kwargs):
        request = factory.get('/', params, **kwargs)
        response = self.view(request).render()
        data = json.loads(response.content)
        self.assertEqual(len(data['features']),
                         PaginatedGeoListView.paginate_by)
        self.assertEqual(data['count'], len(self.qs))
        self.assertTrue(*map(data.has_key, ('previous', 'next')))
        return data

    def test_paginate(self):
        self._test_paginate({'page': 2})

    def test_paginate_geojson(self):
        data = self._test_paginate(
            {'page': 1}, HTTP_ACCEPT=GeoJSONRenderer.media_type)
        self.assertEqual(data['type'], 'FeatureCollection')
        self.assertIn('crs', data)


class RasterListViewTestCase(RasterStoreTestBase):
    def setUp(self):
        super(RasterListViewTestCase, self).setUp()
        self.view = generics.RasterListView.as_view(model=RasterStore)

    def test_list_json(self):
        with Raster(self.qs[0].image.path) as r:
            imdata = r.array().tolist()
            g = r.envelope.polygon.__geo_interface__
            sref_wkt = str(r.sref)
        request = factory.get('/')
        response = self.view(request).render()
        d = json.loads(response.content)
        expected = [{'image': imdata, 'geom': g, 'srs': sref_wkt}]
        self.assertEqual(*map(len, (d, expected)))
        self.assertDictContainsSubset(expected[0], d[0])

    def test_list_zip(self):
        request = factory.get('/', {'format': 'img.zip'})
        response = self.view(request)
        self.assertTrue(response.streaming)
        bio = io.BytesIO(''.join(response.streaming_content))
        zf = zipfile.ZipFile(bio)
        self.assertEqual(len(zf.filelist), len(self.qs))
