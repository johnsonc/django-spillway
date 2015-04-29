from django.http import StreamingHttpResponse
from rest_framework.generics import ListAPIView, ListCreateAPIView, RetrieveAPIView
from rest_framework.settings import api_settings

from spillway import filters, forms, mixins, pagination, renderers, serializers

_default_filters = tuple(api_settings.DEFAULT_FILTER_BACKENDS)
_default_renderers = tuple(api_settings.DEFAULT_RENDERER_CLASSES)


class BaseGeoView(object):
    """Base view for models with geometry fields."""
    model_serializer_class = serializers.FeatureSerializer
    pagination_serializer_class = pagination.PaginatedFeatureSerializer
    filter_backends = _default_filters + (
        filters.SpatialLookupFilter, filters.GeoQuerySetFilter)
    renderer_classes = _default_renderers + (
        renderers.GeoJSONRenderer, renderers.KMLRenderer, renderers.KMZRenderer)


class GeoDetailView(BaseGeoView, RetrieveAPIView):
    """Generic detail view providing vector geometry representations."""


class GeoListView(BaseGeoView, ListAPIView):
    """Generic view for listing a geoqueryset."""


class GeoListCreateAPIView(BaseGeoView, ListCreateAPIView):
    """Generic view for listing or creating geomodel instances."""


class BaseRasterView(mixins.QueryFormMixin):
    """Base view for raster models."""
    model_serializer_class = serializers.RasterModelSerializer
    query_form_class = forms.RasterQueryForm
    filter_backends = _default_filters

    def finalize_response(self, request, response, *args, **kwargs):
        response = super(BaseRasterView, self).finalize_response(
            request, response, *args, **kwargs)
        # Use streaming responses for GDAL formats.
        if isinstance(response.accepted_renderer,
                      renderers.gdal.BaseGDALRenderer):
            headers = response._headers
            response = StreamingHttpResponse(response.rendered_content)
            response._headers = headers
        return response

    def get_renderer_context(self):
        context = super(BaseRasterView, self).get_renderer_context()
        context.update(params=self.clean_params())
        return context


class RasterDetailView(BaseRasterView, RetrieveAPIView):
    """View providing access to a Raster model instance."""
    renderer_classes = _default_renderers + (
        renderers.GeoTIFFRenderer,
        renderers.HFARenderer,
    )


class RasterListView(BaseRasterView, ListAPIView):
    """View providing access to a Raster model QuerySet."""
    filter_backends = _default_filters + (filters.SpatialLookupFilter,)
    renderer_classes = _default_renderers + (
        renderers.GeoTIFFZipRenderer,
        renderers.HFAZipRenderer,
    )
