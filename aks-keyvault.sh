az login

rgName='aks-solution'
aksName='rkaks'
aksName='rkaksdev'
location='canadacentral'

az aks list -g $rgName -o table 
az aks get-credentials -g $rgName -n $aksName --admin --overwrite-existing
az aks get-credentials -g aks-solution -n rkaksdev 

