import pytest
import os
import tarfile
import xarray as xr
import numpy as np
from contextlib import contextmanager
import py
import tempfile
from glob import glob

import xgcm

_TESTDATA_FILENAME = 'testdata.tar.gz'
_TESTDATA_ITERS = [39600, ]
_TESTDATA_DELTAT = 86400

_EXPECTED_GRID_VARS = ['XC', 'YC', 'XG', 'YG', 'Zl', 'Zu', 'Z', 'Zp1', 'dxC',
                       'rAs', 'rAw', 'Depth', 'rA', 'dxG', 'dyG', 'rAz', 'dyC',
                       'PHrefC', 'drC', 'PHrefF', 'drF',
                       'hFacS', 'hFacC', 'hFacW']


_xc_meta_content = """ simulation = { 'global_oce_latlon' };
 nDims = [   2 ];
 dimList = [
    90,    1,   90,
    40,    1,   40
 ];
 dataprec = [ 'float32' ];
 nrecords = [     1 ];
"""


@contextmanager
def hide_file(origdir, *basenames):
    """Temporarily hide files within the context."""
    # make everything a py.path.local
    tmpdir = py.path.local(tempfile.mkdtemp())
    origdir = py.path.local(origdir)
    oldpaths = [origdir.join(basename) for basename in basenames]
    newpaths = [tmpdir.join(basename) for basename in basenames]

    # move the files
    for oldpath, newpath in zip(oldpaths, newpaths):
        oldpath.rename(newpath)

    yield

    # move them back
    for oldpath, newpath in zip(oldpaths, newpaths):
        newpath.rename(oldpath)


# parameterized fixture are complicated
# http://docs.pytest.org/en/latest/fixture.html#fixture-parametrize

# dictionary of archived experiments and some expected properties
_experiments = {
    'global_oce_latlon': {'shape': (15, 40, 90), 'test_iternum': 39600,
                          'first_values': {'XC': 2},
                          'layers': {'1RHO': 31},
                          'diagnostics': ('DiagGAD-T',
                              ['TOTTTEND', 'ADVr_TH', 'ADVx_TH', 'ADVy_TH',
                               'DFrE_TH', 'DFxE_TH', 'DFyE_TH', 'DFrI_TH',
                               'UTHMASS', 'VTHMASS', 'WTHMASS'])},
    'barotropic_gyre': {'shape': (1, 60, 60), 'test_iternum': 10,
                          'first_values': {'XC': 10000.0},
                        'all_iters': [0, 10],
                        'prefixes': ['T', 'S', 'Eta', 'U', 'V', 'W']},
    'internal_wave': {'shape': (20, 1, 30), 'test_iternum': 100,
                      'first_values': {'XC': 109.01639344262296},
                      'all_iters': [0, 100, 200],
                      'ref_date': "1990-1-1 0:0:0",
                      'delta_t': 60,
                      'expected_time':[
                        (0, np.datetime64('1990-01-01T00:00:00.000000000')),
                        (1, np.datetime64('1990-01-01T01:40:00.000000000'))],
                      # these diagnostics won't load because not all levels
                      # where output...no idea how to overcome that bug
                      # 'diagnostics': ('diagout1', ['UVEL', 'VVEL']),
                      'prefixes': ['T', 'S', 'Eta', 'U', 'V', 'W']}
}


def setup_mds_dir(tmpdir_factory, request):
    """Helper function for setting up test cases."""
    expt_name = request.param
    expected_results = _experiments[expt_name]
    target_dir = str(tmpdir_factory.mktemp('mdsdata'))
    data_dir = os.path.dirname(request.module.__file__)
    return untar(data_dir, expt_name, target_dir), expected_results


def untar(data_dir, basename, target_dir):
    """Unzip a tar file into the target directory. Return path to unzipped
    directory."""
    datafile = os.path.join(data_dir, basename + '.tar.gz')
    if not os.path.exists(datafile):
        raise IOError('Could not find data file %s' % datafile)
    tar = tarfile.open(datafile)
    tar.extractall(target_dir)
    tar.close()
    # subdirectory where file should have been untarred.
    # assumes the directory is the same name as the tar file itself.
    # e.g. testdata.tar.gz --> testdata/
    fulldir = os.path.join(target_dir, basename)
    if not os.path.exists(fulldir):
        raise IOError('Could not find tar file output dir %s' % fulldir)
    # the actual data lives in a file called testdata
    return fulldir


# find the tar archive in the test directory
# http://stackoverflow.com/questions/29627341/pytest-where-to-store-expected-data
@pytest.fixture(scope='module', params=_experiments.keys())
def all_mds_datadirs(tmpdir_factory, request):
    return setup_mds_dir(tmpdir_factory, request)


@pytest.fixture(scope='module', params=['barotropic_gyre', 'internal_wave'])
def multidim_mds_datadirs(tmpdir_factory, request):
    return setup_mds_dir(tmpdir_factory, request)

@pytest.fixture(scope='module', params=['global_oce_latlon'])
def mds_datadirs_with_diagnostics(tmpdir_factory, request):
    return setup_mds_dir(tmpdir_factory, request)


@pytest.fixture(scope='module', params=['internal_wave'])
def mds_datadirs_with_refdate(tmpdir_factory, request):
    return setup_mds_dir(tmpdir_factory, request)


@pytest.fixture(scope='module', params=['global_oce_latlon'])
def layers_mds_datadirs(tmpdir_factory, request):
    return setup_mds_dir(tmpdir_factory, request)


def test_parse_meta(tmpdir):
    """Check the parsing of MITgcm .meta into python dictionary."""

    from xgcm.models.mitgcm.utils import parse_meta_file
    p = tmpdir.join("XC.meta")
    p.write(_xc_meta_content)
    fname = str(p)
    result = parse_meta_file(fname)
    expected = {
        'nrecords': 1,
        'basename': 'XC',
        'simulation': "'global_oce_latlon'",
        'dimList': [[90, 1, 90], [40, 1, 40]],
        'nDims': 2,
        'dataprec': np.dtype('float32')
    }
    for k, v in expected.items():
        assert result[k] == v


def test_read_raw_data(tmpdir):
    """Check our utility for reading raw data."""

    from xgcm.models.mitgcm.utils import read_raw_data
    shape = (2, 4)
    for dtype in [np.dtype('f8'), np.dtype('f4'), np.dtype('i4')]:
        # create some test data
        testdata = np.zeros(shape, dtype)
        # write to a file
        datafile = tmpdir.join("tmp.data")
        datafile.write_binary(testdata.tobytes())
        fname = str(datafile)
        # now test the function
        data = read_raw_data(fname, dtype, shape)
        np.testing.assert_allclose(data, testdata)
        # interestingly, memmaps are also ndarrays, but not vice versa
        assert isinstance(data, np.ndarray) and not isinstance(data, np.memmap)
        # check memmap
        mdata = read_raw_data(fname, dtype, shape, use_mmap=True)
        assert isinstance(mdata, np.memmap)

    # make sure errors are correct
    wrongshape = (2, 5)
    with pytest.raises(IOError):
        _ = read_raw_data(fname, dtype, wrongshape)


# a meta test
def test_file_hiding(all_mds_datadirs):
    dirname, _ = all_mds_datadirs
    basenames = ['XC.data', 'XC.meta']
    for basename in basenames:
        assert os.path.exists(os.path.join(dirname, basename))
    with hide_file(dirname, *basenames):
        for basename in basenames:
            assert not os.path.exists(os.path.join(dirname, basename))
    for basename in basenames:
        assert os.path.exists(os.path.join(dirname, basename))


def test_read_mds(all_mds_datadirs):
    """Check that we can read mds data from .meta / .data pairs"""

    dirname, expected = all_mds_datadirs

    from xgcm.models.mitgcm.utils import read_mds

    prefix = 'XC'
    basename = os.path.join(dirname, prefix)
    res = read_mds(basename)
    assert isinstance(res, dict)
    assert prefix in res
    # should be memmap by default
    assert isinstance(res[prefix], np.memmap)

    # try some options
    res = read_mds(basename, force_dict=False)
    assert isinstance(res, np.memmap)
    res = read_mds(basename, force_dict=False, use_mmap=False)
    assert isinstance(res, np.ndarray)

    # make sure endianness works
    testval = res.ravel()[0]
    res_endian = read_mds(basename, force_dict=False, use_mmap=False,
                          endian='<')
    testval_endian = res_endian.ravel()[0]
    assert testval != testval_endian

    # try reading with iteration number
    prefix = 'T'
    basename = os.path.join(dirname, prefix)
    iternum = expected['test_iternum']
    res = read_mds(basename, iternum=iternum)
    assert prefix in res


def test_open_mdsdataset_minimal(all_mds_datadirs):
    """Create a minimal xarray object with only dimensions in it."""

    dirname, expected = all_mds_datadirs

    ds = xgcm.models.mitgcm.mds_store.open_mdsdataset(
            dirname, iters=None, read_grid=False)

    # the expected dimensions of the dataset
    nz, ny, nx = expected['shape']
    coords = {'i': np.arange(nx),
              'i_g': np.arange(nx),
              # 'i_z': np.arange(nx),
              'j': np.arange(ny),
              'j_g': np.arange(ny),
              # 'j_z': np.arange(ny),
              'k': np.arange(nz),
              'k_u': np.arange(nz),
              'k_l': np.arange(nz),
              'k_p1': np.arange(nz+1)}

    if 'layers' in expected:
        for layer_name, n_layers in expected['layers'].items():
            for suffix, offset in zip(['bounds', 'center', 'interface'],
                                      [0, -1, -2]):
                dimname = 'l' + layer_name[0] + '_' + suffix[0]
                index = np.arange(n_layers + offset)
                coords[dimname] = index

    ds_expected = xr.Dataset(coords=coords)

    assert ds_expected.equals(ds)


def test_read_grid(all_mds_datadirs):
    """Make sure we read all the grid variables."""
    dirname, expected = all_mds_datadirs
    ds = xgcm.models.mitgcm.mds_store.open_mdsdataset(
                dirname, iters=None, read_grid=True)

    for vname in _EXPECTED_GRID_VARS:
        assert vname in ds


def test_values_and_endianness(all_mds_datadirs):
    """Make sure we read all the grid variables."""
    dirname, expected = all_mds_datadirs

    # default endianness
    ds = xgcm.models.mitgcm.mds_store.open_mdsdataset(
                dirname, iters=None, read_grid=True)
    # now reverse endianness
    ds_le = xgcm.models.mitgcm.mds_store.open_mdsdataset(
                dirname, iters=None, read_grid=True, endian='<')

    for vname, val in expected['first_values'].items():
        assert ds[vname].values.ravel()[0] == val
        val_le = np.array(val, ds[vname].dtype).newbyteorder('<').squeeze()
        assert ds_le[vname].values.ravel()[0] == val_le


def test_swap_dims(all_mds_datadirs):
    """Make sure we read all the grid variables."""

    dirname, expected = all_mds_datadirs
    ds = xgcm.models.mitgcm.mds_store.open_mdsdataset(
                dirname, iters=None, read_grid=True, swap_dims=True)

    expected_dims = ['XC', 'XG', 'YC', 'YG', 'Z', 'Zl', 'Zp1', 'Zu']

    # add extra layers dimensions if needed
    if 'layers' in expected:
        for layer_name in expected['layers']:
            extra_dims = ['layer_' + layer_name + suffix for suffix in
                          ['_bounds', '_center', '_interface']]
            expected_dims += extra_dims

    assert ds.dims.keys() == expected_dims


def test_prefixes(all_mds_datadirs):
    """Make sure we read all the grid variables."""

    dirname, expected = all_mds_datadirs
    prefixes = ['U', 'V', 'W', 'T', 'S', 'PH']  # , 'PHL', 'Eta']
    iters = [expected['test_iternum']]
    ds = xgcm.models.mitgcm.mds_store.open_mdsdataset(
                dirname, iters=iters, prefix=prefixes,
                read_grid=False)

    for p in prefixes:
        assert p in ds

    # try with dim swapping
    ds = xgcm.models.mitgcm.mds_store.open_mdsdataset(
                dirname, iters=iters, prefix=prefixes,
                read_grid=True, swap_dims=True)

    for p in prefixes:
        assert p in ds


def test_multiple_iters(multidim_mds_datadirs):
    """Test ability to load multiple iters into a single dataset."""

    dirname, expected = multidim_mds_datadirs
    # first try specifying the iters
    ds = xgcm.models.mitgcm.mds_store.open_mdsdataset(
        dirname, read_grid=False,
        iters=expected['all_iters'],
        prefix=expected['prefixes'])
    assert list(ds.iter.values) == expected['all_iters']

    # now infer the iters, should be the same
    ds2 = xgcm.models.mitgcm.mds_store.open_mdsdataset(
        dirname, read_grid=False, iters='all',
        prefix=expected['prefixes'])
    assert ds.equals(ds2)

    # In the test datasets, there is no PHL.0000000000.data file.
    # By default we infer the prefixes from the first iteration number, so this
    # leads to an error.
    # (Need to specify iters because there is some diagnostics output with
    # weird iterations numbers present in some experiments.)
    with pytest.raises(IOError):
        ds = xgcm.models.mitgcm.mds_store.open_mdsdataset(
            dirname, read_grid=False, iters=expected['all_iters'])

    # now hide all the PH and PHL files: should be able to infer prefixes fine
    missing_files = [os.path.basename(f)
                     for f in glob(os.path.join(dirname, 'PH*.0*data'))]
    with hide_file(dirname, *missing_files):
        ds = xgcm.models.mitgcm.mds_store.open_mdsdataset(
            dirname, read_grid=False, iters=expected['all_iters'])


def test_date_parsing(mds_datadirs_with_refdate):
    """Verify that time information is decoded properly."""
    dirname, expected = mds_datadirs_with_refdate

    ds = xgcm.open_mdsdataset(dirname, iters='all', prefix=['S'],
                              ref_date=expected['ref_date'], read_grid=False,
                              delta_t=expected['delta_t'])

    for i, date in expected['expected_time']:
        assert ds.time[i].values == date


def test_parse_diagnostics(all_mds_datadirs):
    """Make sure we can parse the available_diagnostics.log file."""
    from xgcm.models.mitgcm.utils import parse_available_diagnostics
    dirname, expected = all_mds_datadirs
    diagnostics_fname = os.path.join(dirname, 'available_diagnostics.log')
    ad = parse_available_diagnostics(diagnostics_fname)

    # a somewhat random sampling of diagnostics
    expected_diags = {
        'UVEL': {'dims': ['k', 'j', 'i_g'],
                 'attrs': {'units': 'm/s',
                           'long_name': 'Zonal Component of Velocity (m/s)',
                           'standard_name': 'UVEL'}},
        'TFLUX': {'dims': ['j', 'i'],
                  'attrs': {'units': 'W/m^2',
                            'long_name': 'total heat flux (match heat-content '
                            'variations), >0 increases theta',
                            'standard_name': 'TFLUX'}}
     }

    for key, val in expected_diags.items():
        assert ad[key] == val


def test_diagnostics(mds_datadirs_with_diagnostics):
    """Try reading dataset with diagnostics output."""
    dirname, expected = mds_datadirs_with_diagnostics

    diag_prefix, expected_diags = expected['diagnostics']
    ds = xgcm.models.mitgcm.mds_store.open_mdsdataset(dirname,
                                                      read_grid=False,
                                                      iters='all',
                                                      prefix=[diag_prefix])
    for diagname in expected_diags:
        assert diagname in ds


def test_layers_diagnostics(layers_mds_datadirs):
    """Try reading dataset with layers output."""
    dirname, expected = layers_mds_datadirs
    ds = xgcm.models.mitgcm.mds_store.open_mdsdataset(dirname, iters='all')
    layer_name = expected['layers'].keys()[0]
    layer_id = 'l' + layer_name[0]
    for suf in ['bounds', 'center', 'interface']:
        assert ('layer_' + layer_name + '_' + suf) in ds
        assert (layer_id + '_' + suf[0]) in ds.dims

    # a few random expected variables
    expected_vars = {'LaUH' + layer_name:
                     ('time', layer_id + '_c', 'j', 'i_g'),
                     'LaVH' + layer_name:
                     ('time', layer_id + '_c', 'j_g', 'i'),
                     'LaTs' + layer_name:
                     ('time', layer_id + '_i', 'j', 'i')}
    for var, dims in expected_vars.items():
        assert var in ds
        assert ds[var].dims == dims


# @pytest.mark.skipif(True, reason="Not ready")
# def test_open_mdsdataset_full(all_mds_datadirs):
#     # most basic test: make sure we can open an mds dataset
#     ds = xgcm.open_mdsdataset(all_mds_datadirs,
#             _TESTDATA_ITERS, deltaT=_TESTDATA_DELTAT)
#     #print(ds)
#
#     # check just a single value
#     assert ds['X'][0].values == 2.0
#
#     # check little endianness
#     ds = xgcm.open_mdsdataset(all_mds_datadirs,
#             _TESTDATA_ITERS, deltaT=_TESTDATA_DELTAT, endian="<")
#     assert ds['X'][0].values == 8.96831017167883e-44
#     #print(ds)
