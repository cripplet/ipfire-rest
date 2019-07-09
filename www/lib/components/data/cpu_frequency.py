import json

from lib.components import ipfire_config
from lib.components import shared
from lib.components.data import shared as shared_data


def GetCPUFrequencyData(step):
  root = ipfire_config.GetIPFireConfig()['main']['rrdlog']
  command = shared_data.GetRRDCommandArgs(
      start_time=step * 20,
      step=step
  ) + sum([
      [
          'DEF:cpu{core}={root}/collectd/localhost/cpufreq/cpufreq-{core}.rrd:value:AVERAGE'.format(
              core=i,
              root=root),
          'XPORT:cpu{core}:cpu{core}'.format(core=i),
      ] for i in range(shared_data.GetCoreCount())
  ], [])
  return json.loads(
    shared.GetSysOutput(' '.join(command))
  )
